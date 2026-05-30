"""
Gold & Dollar Telegram Bot — v2.0
بوت متطور لمتابعة XAUUSD والدولار
"""

import asyncio
import json
import logging
import os
import sqlite3
import feedparser
import httpx
import pytz
from datetime import datetime, timedelta
from telegram import (
    Bot, Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
)
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler, ContextTypes
)
from apscheduler.schedulers.asyncio import AsyncIOScheduler

# ─── Config ──────────────────────────────────────────────────────────────────
TOKEN       = os.getenv("TELEGRAM_BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
ADMIN_ID    = int(os.getenv("ADMIN_CHAT_ID", "0"))   # your personal chat id
MOROCCO_TZ  = pytz.timezone("Africa/Casablanca")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s"
)
logger = logging.getLogger("GoldBot")

# ─── Database ─────────────────────────────────────────────────────────────────
DB_PATH = "goldbot.db"

def db_init():
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            chat_id     INTEGER PRIMARY KEY,
            username    TEXT,
            first_name  TEXT,
            joined_at   TEXT,
            active      INTEGER DEFAULT 1,
            notify_news INTEGER DEFAULT 1,
            notify_ny   INTEGER DEFAULT 1,
            notify_econ INTEGER DEFAULT 1,
            lang        TEXT DEFAULT 'ar'
        );
        CREATE TABLE IF NOT EXISTS sent_news (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            title_hash TEXT UNIQUE,
            sent_at    TEXT
        );
        CREATE TABLE IF NOT EXISTS econ_alerts (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            event_name TEXT,
            event_time TEXT,
            impact     TEXT,
            actual     TEXT,
            forecast   TEXT,
            previous   TEXT,
            alerted    INTEGER DEFAULT 0
        );
    """)
    con.commit(); con.close()

def db_register_user(chat_id: int, username: str, first_name: str):
    con = sqlite3.connect(DB_PATH)
    con.execute("""
        INSERT INTO users (chat_id, username, first_name, joined_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(chat_id) DO UPDATE SET active=1, username=excluded.username
    """, (chat_id, username or "", first_name or "", datetime.now().isoformat()))
    con.commit(); con.close()

def db_get_active_users(pref_col: str = None) -> list[int]:
    con = sqlite3.connect(DB_PATH)
    if pref_col:
        rows = con.execute(
            f"SELECT chat_id FROM users WHERE active=1 AND {pref_col}=1"
        ).fetchall()
    else:
        rows = con.execute("SELECT chat_id FROM users WHERE active=1").fetchall()
    con.close()
    return [r[0] for r in rows]

def db_get_user_prefs(chat_id: int) -> dict:
    con = sqlite3.connect(DB_PATH)
    row = con.execute(
        "SELECT notify_news, notify_ny, notify_econ, lang FROM users WHERE chat_id=?",
        (chat_id,)
    ).fetchone()
    con.close()
    if row:
        return {"notify_news": row[0], "notify_ny": row[1],
                "notify_econ": row[2], "lang": row[3]}
    return {"notify_news": 1, "notify_ny": 1, "notify_econ": 1, "lang": "ar"}

def db_update_pref(chat_id: int, col: str, val: int):
    con = sqlite3.connect(DB_PATH)
    con.execute(f"UPDATE users SET {col}=? WHERE chat_id=?", (val, chat_id))
    con.commit(); con.close()

def db_is_news_sent(title_hash: str) -> bool:
    con = sqlite3.connect(DB_PATH)
    r = con.execute("SELECT 1 FROM sent_news WHERE title_hash=?", (title_hash,)).fetchone()
    con.close()
    return r is not None

def db_mark_news_sent(title_hash: str):
    con = sqlite3.connect(DB_PATH)
    con.execute("INSERT OR IGNORE INTO sent_news (title_hash, sent_at) VALUES (?,?)",
                (title_hash, datetime.now().isoformat()))
    # keep only last 500
    con.execute("DELETE FROM sent_news WHERE id NOT IN (SELECT id FROM sent_news ORDER BY id DESC LIMIT 500)")
    con.commit(); con.close()

def db_get_stats() -> dict:
    con = sqlite3.connect(DB_PATH)
    total   = con.execute("SELECT COUNT(*) FROM users WHERE active=1").fetchone()[0]
    sent    = con.execute("SELECT COUNT(*) FROM sent_news").fetchone()[0]
    con.close()
    return {"users": total, "sent": sent}

# ─── RSS / News ───────────────────────────────────────────────────────────────
RSS_FEEDS = [
    ("FXStreet Gold",   "https://www.fxstreet.com/rss/news/gold"),
    ("FXStreet USD",    "https://www.fxstreet.com/rss/news/us-dollar"),
    ("Investing Gold",  "https://www.investing.com/rss/news_301.rss"),
    ("Reuters Mkts",    "https://feeds.reuters.com/reuters/businessNews"),
    ("MarketWatch",     "https://feeds.content.dowjones.io/public/rss/mw_realtimeheadlines"),
    ("ForexLive",       "https://www.forexlive.com/feed/news"),
]

GOLD_KW   = ["gold","xauusd","xau","bullion","ounce","الذهب","معدن"]
USD_KW    = ["dollar","usd","fed","fomc","federal reserve","interest rate",
             "inflation","cpi","nfp","payroll","powell","yellen","الدولار",
             "التضخم","الفيدرالي"]
HIGH_KW   = ["fomc","federal reserve","nfp","cpi","ppi","gdp","rate decision",
             "payroll","الفيدرالي","قرار الفائدة"]

BULLISH_W = ["rises","surges","gains","jumps","rally","bullish","high","strong",
             "upside","record","positive","beat","above","outperform","ارتفع",
             "صعود","قوي","فاق التوقعات","إيجابي"]
BEARISH_W = ["falls","drops","declines","pressure","bearish","weak","selloff",
             "downside","negative","miss","below","انخفض","هبوط","ضعيف",
             "دون التوقعات","سلبي"]

def sentiment(text: str) -> tuple[str, str, int]:
    t = text.lower()
    b = sum(1 for w in BULLISH_W if w in t)
    s = sum(1 for w in BEARISH_W if w in t)
    if b > s:
        return "🟢 Bullish صعودي", "ارتفاع محتمل للذهب / ضعف الدولار", 1
    elif s > b:
        return "🔴 Bearish هبوطي", "هبوط محتمل للذهب / قوة الدولار", -1
    return "🟡 Neutral محايد", "السوق بانتظار مزيد من البيانات", 0

def is_relevant(title: str, summary: str) -> tuple[bool, str, bool]:
    text = (title + " " + summary).lower()
    high = any(k in text for k in HIGH_KW)
    if any(k in text for k in GOLD_KW):
        return True, "GOLD", high
    if any(k in text for k in USD_KW):
        return True, "USD", high
    return False, "", False

def title_hash(title: str) -> str:
    import hashlib
    return hashlib.md5(title.strip().lower().encode()).hexdigest()[:16]

async def fetch_news(limit: int = 8) -> list[dict]:
    items = []
    async with httpx.AsyncClient(timeout=12, follow_redirects=True) as client:
        for name, url in RSS_FEEDS:
            try:
                r = await client.get(url, headers={"User-Agent": "Mozilla/5.0"})
                feed = feedparser.parse(r.text)
                for entry in feed.entries[:12]:
                    t   = entry.get("title", "")
                    s   = entry.get("summary", "")[:300]
                    lnk = entry.get("link", "")
                    rel, asset, high = is_relevant(t, s)
                    if rel:
                        sent_lbl, impact_lbl, sent_val = sentiment(t + " " + s)
                        items.append({
                            "source": name, "asset": asset, "high": high,
                            "title": t[:130], "link": lnk,
                            "sentiment": sent_lbl, "impact": impact_lbl,
                            "sent_val": sent_val,
                            "hash": title_hash(t)
                        })
            except Exception as e:
                logger.warning(f"Feed {name}: {e}")
    seen, unique = set(), []
    for it in items:
        if it["hash"] not in seen:
            seen.add(it["hash"]); unique.append(it)
    return unique[:limit]

# ─── Economic Calendar (ForexFactory public API) ──────────────────────────────
ECON_EVENTS = [
    # (keyword, impact_label, emoji)
    ("non-farm payroll",   "HIGH 🔥",  "💼"),
    ("nfp",                "HIGH 🔥",  "💼"),
    ("cpi",                "HIGH 🔥",  "📈"),
    ("consumer price",     "HIGH 🔥",  "📈"),
    ("fomc",               "HIGH 🔥",  "🏦"),
    ("federal funds",      "HIGH 🔥",  "🏦"),
    ("interest rate",      "HIGH 🔥",  "🏦"),
    ("gdp",                "MED ⚡",   "📊"),
    ("ppi",                "MED ⚡",   "🏭"),
    ("retail sales",       "MED ⚡",   "🛒"),
    ("ism",                "MED ⚡",   "🏗️"),
    ("jobless claims",     "MED ⚡",   "👥"),
    ("pce",                "HIGH 🔥",  "💰"),
    ("durable goods",      "LOW ℹ️",   "📦"),
]

async def fetch_economic_calendar() -> list[dict]:
    """Fetch upcoming high-impact events from ForexFactory RSS"""
    events = []
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(
                "https://nfs.faireconomy.media/ff_calendar_thisweek.json",
                headers={"User-Agent": "Mozilla/5.0"}
            )
            data = r.json()
            now = datetime.now(MOROCCO_TZ)
            for ev in data:
                if ev.get("impact") not in ("High", "Medium"):
                    continue
                currency = ev.get("currency", "")
                if currency not in ("USD", "XAU"):
                    continue
                try:
                    ev_time = datetime.fromisoformat(ev["date"].replace("Z", "+00:00"))
                    ev_time = ev_time.astimezone(MOROCCO_TZ)
                except Exception:
                    continue
                if ev_time < now:
                    continue
                events.append({
                    "name":     ev.get("title", ""),
                    "currency": currency,
                    "impact":   ev.get("impact", ""),
                    "time":     ev_time,
                    "forecast": ev.get("forecast", "—"),
                    "previous": ev.get("previous", "—"),
                })
            events.sort(key=lambda x: x["time"])
    except Exception as e:
        logger.warning(f"Economic calendar error: {e}")
    return events[:10]

# ─── Message formatters ───────────────────────────────────────────────────────
def fmt_news_block(news: list[dict], header: str) -> str:
    now = datetime.now(MOROCCO_TZ).strftime("%d/%m/%Y %H:%M")
    lines = [f"*{header}*", f"🕐 _{now} (توقيت المغرب)_", ""]
    if not news:
        lines.append("⏳ لا توجد أخبار جديدة في الوقت الحالي.")
        return "\n".join(lines)
    for i, n in enumerate(news, 1):
        icon = "🥇" if n["asset"] == "GOLD" else "💵"
        hot  = "🔥 " if n["high"] else ""
        lines += [
            f"*{i}\\. {hot}{icon} {n['asset']} — {n['source']}*",
            f"📌 {n['title']}",
            f"{n['sentiment']}",
            f"💡 _{n['impact']}_",
        ]
        if n["link"]:
            lines.append(f"🔗 [اقرأ المزيد]({n['link']})")
        lines.append("")
    return "\n".join(lines)

def fmt_analysis(news: list[dict]) -> str:
    now = datetime.now(MOROCCO_TZ).strftime("%d/%m/%Y %H:%M")
    gold_items = [n for n in news if n["asset"] == "GOLD"]
    usd_items  = [n for n in news if n["asset"] == "USD"]

    def score(items):
        total = sum(n["sent_val"] for n in items)
        bull  = sum(1 for n in items if n["sent_val"] > 0)
        bear  = sum(1 for n in items if n["sent_val"] < 0)
        return total, bull, bear

    lines = ["📊 *تحليل السوق الشامل*", f"🕐 _{now}_", "━━━━━━━━━━━━━━━━━━━━", ""]

    for label, icon, items in [("XAUUSD — الذهب", "🥇", gold_items), ("USD — الدولار", "💵", usd_items)]:
        if not items:
            lines += [f"*{icon} {label}:* لا توجد بيانات كافية", ""]
            continue
        total, bull, bear = score(items)
        if total > 0:
            overall = "🟢 *Bullish* — إعداد للشراء"
            bias    = "ارتفاع محتمل — راقب مستويات المقاومة"
        elif total < 0:
            overall = "🔴 *Bearish* — إعداد للبيع"
            bias    = "هبوط محتمل — راقب مستويات الدعم"
        else:
            overall = "🟡 *Neutral* — انتظر تأكيد"
            bias    = "السوق في توازن — تجنب الدخول العشوائي"
        lines += [
            f"*{icon} {label}*",
            f"الحكم: {overall}",
            f"📈 Bullish: {bull} | 📉 Bearish: {bear} | Score: {total:+d}",
            f"💡 _{bias}_",
            ""
        ]

    # Combined XAUUSD bias
    all_scores = [n["sent_val"] for n in news]
    if all_scores:
        net = sum(all_scores)
        if net > 1:
            combined = "🟢 الذهب في صعود — الدولار ضعيف"
        elif net < -1:
            combined = "🔴 الذهب تحت ضغط — الدولار قوي"
        else:
            combined = "🟡 توازن — انتظر catalyst"
        lines += ["━━━━━━━━━━━━━━━━━━━━",
                  f"*🎯 الـ Bias الإجمالي:* {combined}", ""]
    lines += [
        "⚠️ _هذا التحليل إرشادي — دير دائماً إدارة رأسمال مزيانة_"
    ]
    return "\n".join(lines)

def fmt_ny_alert(news: list[dict], econ: list[dict]) -> str:
    today = datetime.now(MOROCCO_TZ).strftime("%d/%m/%Y")
    gold  = [n for n in news if n["asset"] == "GOLD"]
    usd   = [n for n in news if n["asset"] == "USD"]

    lines = [
        "⚡️ *تنبيه جلسة نيويورك*",
        f"🗓 _{today}_",
        "━━━━━━━━━━━━━━━━━━━━━━━━",
        "🕒 *باقي 30 دقيقة على افتتاح نيويورك*",
        "🌍 _(15:00 توقيت المغرب / 14:00 GMT)_",
        ""
    ]

    # Economic events today
    now = datetime.now(MOROCCO_TZ)
    today_events = [e for e in econ if e["time"].date() == now.date()]
    if today_events:
        lines.append("🗓 *البيانات الاقتصادية اليوم:*")
        for ev in today_events[:4]:
            t     = ev["time"].strftime("%H:%M")
            imp   = "🔥" if ev["impact"] == "High" else "⚡"
            lines.append(f"  {imp} {t} — {ev['name']} ({ev['currency']}) | توقع: {ev['forecast']}")
        lines.append("")

    # Gold news
    if gold:
        lines.append("🥇 *XAUUSD — الذهب:*")
        net = sum(n["sent_val"] for n in gold)
        for n in gold[:2]:
            lines += [f"  • _{n['title']}_", f"  {n['sentiment']}"]
        bias = "🟢 Bullish" if net > 0 else "🔴 Bearish" if net < 0 else "🟡 Neutral"
        lines += [f"  🎯 *Bias الذهب: {bias}*", ""]

    # USD news
    if usd:
        lines.append("💵 *الدولار USD:*")
        net = sum(n["sent_val"] for n in usd)
        for n in usd[:2]:
            lines += [f"  • _{n['title']}_", f"  {n['sentiment']}"]
        bias = "🟢 قوي" if net > 0 else "🔴 ضعيف" if net < 0 else "🟡 محايد"
        lines += [f"  🎯 *Bias الدولار: {bias}*", ""]

    if not gold and not usd:
        lines += ["⏳ لا توجد أخبار مهمة قبيل الجلسة", ""]

    lines += [
        "━━━━━━━━━━━━━━━━━━━━━━━━",
        "📋 *Checklist قبل الدخول:*",
        "☑️ تحقق من S/R على M15",
        "☑️ انتظر تأكيد الشمعة (M5/M1)",
        "☑️ حدد SL و TP قبل الدخول",
        "☑️ لا تخاطر بأكثر من 1-2% للصفقة",
        "",
        "🤝 _تداول بحكمة — حظ موفق يا مصطفى!_ 💪"
    ]
    return "\n".join(lines)

def fmt_calendar(econ: list[dict]) -> str:
    now   = datetime.now(MOROCCO_TZ)
    lines = ["🗓 *التقويم الاقتصادي — هذا الأسبوع*",
             f"🕐 _{now.strftime('%d/%m/%Y %H:%M')}_",
             "━━━━━━━━━━━━━━━━━━━━━━", ""]
    if not econ:
        lines.append("⏳ لا توجد بيانات متاحة حالياً.")
        return "\n".join(lines)
    current_day = None
    for ev in econ:
        day = ev["time"].strftime("%A %d/%m")
        if day != current_day:
            lines += ["", f"📅 *{day}*"]
            current_day = day
        t    = ev["time"].strftime("%H:%M")
        imp  = "🔥 HIGH" if ev["impact"] == "High" else "⚡ MED"
        cur  = "🥇" if ev["currency"] == "XAU" else "💵"
        lines.append(
            f"  {imp} | {t} | {cur} *{ev['name']}*\n"
            f"  توقع: `{ev['forecast']}` | سابق: `{ev['previous']}`"
        )
    lines += ["", "⚠️ _الأوقات بتوقيت المغرب (GMT+1)_"]
    return "\n".join(lines)

# ─── Keyboards ────────────────────────────────────────────────────────────────
def main_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📰 أخبار الآن",    callback_data="news"),
         InlineKeyboardButton("📊 تحليل السوق",   callback_data="analysis")],
        [InlineKeyboardButton("⚡ تنبيه نيويورك", callback_data="ny"),
         InlineKeyboardButton("🗓 التقويم",        callback_data="calendar")],
        [InlineKeyboardButton("⚙️ الإعدادات",      callback_data="settings")],
    ])

def settings_kb(prefs: dict) -> InlineKeyboardMarkup:
    def tog(v): return "✅" if v else "❌"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"{tog(prefs['notify_news'])} أخبار كل ساعة",
                              callback_data="toggle_news")],
        [InlineKeyboardButton(f"{tog(prefs['notify_ny'])} تنبيه نيويورك",
                              callback_data="toggle_ny")],
        [InlineKeyboardButton(f"{tog(prefs['notify_econ'])} تنبيهات البيانات",
                              callback_data="toggle_econ")],
        [InlineKeyboardButton("🔙 رجوع", callback_data="back_main")],
    ])

# ─── Handlers ─────────────────────────────────────────────────────────────────
async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    db_register_user(update.effective_chat.id, user.username, user.first_name)
    name = user.first_name or "Trader"
    await update.message.reply_markdown_v2(
        f"👋 *مرحباً {name}\\!*\n\n"
        f"🤖 _بوت الذهب والدولار — v2\\.0_\n\n"
        f"أنا هنا نوصلك:\n"
        f"• 📰 أخبار XAUUSD والدولار فورية\n"
        f"• 📊 تحليل Bullish/Bearish/Neutral\n"
        f"• ⚡ تنبيه 30 دق قبل جلسة نيويورك\n"
        f"• 🗓 التقويم الاقتصادي HIGH IMPACT\n\n"
        f"🆔 Chat ID: `{update.effective_chat.id}`",
        reply_markup=main_menu_kb()
    )

async def cmd_news(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = await update.message.reply_text("⏳ جاري جلب الأخبار...")
    news = await fetch_news(6)
    text = fmt_news_block(news, "📰 آخر أخبار الذهب والدولار")
    await msg.edit_text(text, parse_mode="Markdown",
                        disable_web_page_preview=True, reply_markup=main_menu_kb())

async def cmd_analysis(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = await update.message.reply_text("📊 جاري التحليل...")
    news = await fetch_news(12)
    text = fmt_analysis(news)
    await msg.edit_text(text, parse_mode="Markdown", reply_markup=main_menu_kb())

async def cmd_ny(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = await update.message.reply_text("⚡️ جاري تجهيز تقرير نيويورك...")
    news, econ = await asyncio.gather(fetch_news(10), fetch_economic_calendar())
    text = fmt_ny_alert(news, econ)
    await msg.edit_text(text, parse_mode="Markdown",
                        disable_web_page_preview=True, reply_markup=main_menu_kb())

async def cmd_calendar(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = await update.message.reply_text("🗓 جاري تحميل التقويم...")
    econ = await fetch_economic_calendar()
    text = fmt_calendar(econ)
    await msg.edit_text(text, parse_mode="Markdown", reply_markup=main_menu_kb())

async def cmd_settings(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    prefs = db_get_user_prefs(update.effective_chat.id)
    await update.message.reply_markdown(
        "⚙️ *الإعدادات* — اختر ما تريد تفعيله أو إيقافه:",
        reply_markup=settings_kb(prefs)
    )

async def cmd_stats(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != ADMIN_ID and ADMIN_ID != 0:
        return
    stats = db_get_stats()
    await update.message.reply_markdown(
        f"📈 *إحصائيات البوت*\n\n"
        f"👥 المستخدمون النشطون: *{stats['users']}*\n"
        f"📨 الأخبار المرسلة: *{stats['sent']}*\n"
        f"🕐 الوقت: {datetime.now(MOROCCO_TZ).strftime('%d/%m/%Y %H:%M')}"
    )

async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_markdown(
        "📖 *الأوامر المتاحة:*\n\n"
        "/news — آخر أخبار الذهب والدولار\n"
        "/analysis — تحليل شامل للسوق\n"
        "/ny — تنبيه جلسة نيويورك\n"
        "/calendar — التقويم الاقتصادي\n"
        "/settings — إعدادات التنبيهات\n"
        "/help — هذه القائمة\n\n"
        "🔔 *التنبيهات التلقائية:*\n"
        "• كل ساعة: أخبار جديدة\n"
        "• 14:30 مغرب: تنبيه نيويورك\n"
        "• 07:00 مغرب: ملخص بداية اليوم\n"
        "• عند صدور CPI/NFP/FOMC: تنبيه فوري 🔥",
        reply_markup=main_menu_kb()
    )

# ─── Callback (inline buttons) ────────────────────────────────────────────────
async def on_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q    = update.callback_query
    data = q.data
    cid  = q.message.chat_id
    await q.answer()

    if data == "news":
        await q.edit_message_text("⏳ جاري جلب الأخبار...", parse_mode="Markdown")
        news = await fetch_news(6)
        text = fmt_news_block(news, "📰 آخر أخبار الذهب والدولار")
        await q.edit_message_text(text, parse_mode="Markdown",
                                  disable_web_page_preview=True, reply_markup=main_menu_kb())

    elif data == "analysis":
        await q.edit_message_text("📊 جاري التحليل...", parse_mode="Markdown")
        news = await fetch_news(12)
        text = fmt_analysis(news)
        await q.edit_message_text(text, parse_mode="Markdown", reply_markup=main_menu_kb())

    elif data == "ny":
        await q.edit_message_text("⚡ جاري تجهيز تقرير نيويورك...", parse_mode="Markdown")
        news, econ = await asyncio.gather(fetch_news(10), fetch_economic_calendar())
        text = fmt_ny_alert(news, econ)
        await q.edit_message_text(text, parse_mode="Markdown",
                                  disable_web_page_preview=True, reply_markup=main_menu_kb())

    elif data == "calendar":
        await q.edit_message_text("🗓 جاري تحميل التقويم...", parse_mode="Markdown")
        econ = await fetch_economic_calendar()
        text = fmt_calendar(econ)
        await q.edit_message_text(text, parse_mode="Markdown", reply_markup=main_menu_kb())

    elif data == "settings":
        prefs = db_get_user_prefs(cid)
        await q.edit_message_text(
            "⚙️ *الإعدادات* — اختر ما تريد تفعيله:",
            parse_mode="Markdown", reply_markup=settings_kb(prefs)
        )

    elif data.startswith("toggle_"):
        col_map = {"toggle_news": "notify_news", "toggle_ny": "notify_ny",
                   "toggle_econ": "notify_econ"}
        col   = col_map[data]
        prefs = db_get_user_prefs(cid)
        new_val = 0 if prefs[col.split("_", 1)[1]] else 1
        db_update_pref(cid, col, new_val)
        prefs = db_get_user_prefs(cid)
        await q.edit_message_text(
            "⚙️ *الإعدادات* — تم الحفظ ✅",
            parse_mode="Markdown", reply_markup=settings_kb(prefs)
        )

    elif data == "back_main":
        await q.edit_message_text(
            "📊 *القائمة الرئيسية* — اختر ما تريد:",
            parse_mode="Markdown", reply_markup=main_menu_kb()
        )

# ─── Scheduled broadcast helpers ─────────────────────────────────────────────
async def broadcast(bot: Bot, text: str, pref_col: str):
    users = db_get_active_users(pref_col)
    for cid in users:
        try:
            await bot.send_message(cid, text, parse_mode="Markdown",
                                   disable_web_page_preview=True)
            await asyncio.sleep(0.05)
        except Exception as e:
            logger.warning(f"Broadcast to {cid} failed: {e}")

# ─── Jobs ─────────────────────────────────────────────────────────────────────
async def job_hourly(bot: Bot):
    news = await fetch_news(4)
    new_items = [n for n in news if not db_is_news_sent(n["hash"])]
    if not new_items:
        logger.info("Hourly: no new items")
        return
    for n in new_items:
        db_mark_news_sent(n["hash"])
    text = fmt_news_block(new_items, "📰 أخبار جديدة — XAUUSD & USD")
    await broadcast(bot, text, "notify_news")
    logger.info(f"Hourly: sent {len(new_items)} new items")

async def job_ny_alert(bot: Bot):
    news, econ = await asyncio.gather(fetch_news(10), fetch_economic_calendar())
    text = fmt_ny_alert(news, econ)
    await broadcast(bot, text, "notify_ny")
    logger.info("NY alert broadcast done")

async def job_morning(bot: Bot):
    news = await fetch_news(6)
    today = datetime.now(MOROCCO_TZ).strftime("%d/%m/%Y")
    text  = fmt_news_block(news, f"🌅 صباح الخير — ملخص {today}")
    await broadcast(bot, text, "notify_news")
    logger.info("Morning summary sent")

async def job_econ_alerts(bot: Bot):
    """Send alert 1h before HIGH-impact USD events"""
    econ = await fetch_economic_calendar()
    now  = datetime.now(MOROCCO_TZ)
    for ev in econ:
        delta = (ev["time"] - now).total_seconds()
        if 3300 < delta < 3900:  # ~55-65 min before
            text = (
                f"⚠️ *تنبيه بيانات اقتصادية مهمة*\n\n"
                f"🔥 *{ev['name']}* ({ev['currency']})\n"
                f"⏰ الوقت: *{ev['time'].strftime('%H:%M')} (مغرب)*\n"
                f"📊 التوقع: `{ev['forecast']}` | السابق: `{ev['previous']}`\n\n"
                f"💡 _هذه البيانات قد تسبب حركة قوية على XAUUSD_\n"
                f"⚠️ _احذر من الدخول قبل الإعلان!_"
            )
            await broadcast(bot, text, "notify_econ")
            logger.info(f"Econ alert sent for: {ev['name']}")

# ─── Main ─────────────────────────────────────────────────────────────────────
async def main():
    db_init()
    logger.info("Database initialized")

    app = Application.builder().token(TOKEN).build()

    # Commands
    app.add_handler(CommandHandler("start",    cmd_start))
    app.add_handler(CommandHandler("news",     cmd_news))
    app.add_handler(CommandHandler("analysis", cmd_analysis))
    app.add_handler(CommandHandler("ny",       cmd_ny))
    app.add_handler(CommandHandler("calendar", cmd_calendar))
    app.add_handler(CommandHandler("settings", cmd_settings))
    app.add_handler(CommandHandler("stats",    cmd_stats))
    app.add_handler(CommandHandler("help",     cmd_help))
    app.add_handler(CallbackQueryHandler(on_callback))

    # Set bot commands menu
    await app.bot.set_my_commands([
        BotCommand("news",     "آخر أخبار الذهب والدولار"),
        BotCommand("analysis", "تحليل السوق الشامل"),
        BotCommand("ny",       "تنبيه جلسة نيويورك"),
        BotCommand("calendar", "التقويم الاقتصادي"),
        BotCommand("settings", "إعدادات التنبيهات"),
        BotCommand("help",     "المساعدة"),
    ])

    bot = app.bot
    scheduler = AsyncIOScheduler(timezone=MOROCCO_TZ)
    # Hourly news at :10 past the hour
    scheduler.add_job(job_hourly,      "cron", minute=10,                 args=[bot])
    # NY alert 30 min before (NY opens 15:00 Morocco)
    scheduler.add_job(job_ny_alert,    "cron", hour=14, minute=30,        args=[bot])
    # Morning summary
    scheduler.add_job(job_morning,     "cron", hour=7,  minute=0,         args=[bot])
    # Economic event alerts — check every 10 min
    scheduler.add_job(job_econ_alerts, "cron", minute="*/10",             args=[bot])
    scheduler.start()

    logger.info("✅ Gold Bot v2.0 started — polling...")
    await app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    asyncio.run(main())
