# 🤖 Gold & Dollar Bot v2.0 — دليل النشر الكامل

## 📁 الملفات
```
bot.py            ← الكود الرئيسي
requirements.txt  ← المكتبات المطلوبة
Procfile          ← إعداد Railway/Render
.env.example      ← متغيرات البيئة
```

---

## الخطوة 1️⃣ — إنشاء البوت على تلغرام

1. افتح تلغرام → ابحث عن **@BotFather**
2. ابعث: `/newbot`
3. اختر اسم: مثلاً `Gold Trader Bot`
4. اختر username: مثلاً `mustafa_xauusd_bot`
5. **احفظ الـ TOKEN** (مثال: `7123456789:AABBcc...`)

---

## الخطوة 2️⃣ — الحصول على Chat ID

1. ابعث أي رسالة للبوت ديالك
2. افتح هذا الرابط في المتصفح (بدّل TOKEN بتوكن ديالك):
   ```
   https://api.telegram.org/botTOKEN/getUpdates
   ```
3. في الجواب ابحث عن: `"chat":{"id":` → هذا هو الـ CHAT_ID

---

## الخطوة 3️⃣ — النشر على Railway (مجاني 100%)

### طريقة GitHub (الأسهل):
1. حمّل الملفات على GitHub repo جديد
2. اذهب لـ https://railway.app → Sign up with GitHub
3. اضغط **New Project** → **Deploy from GitHub repo**
4. اختر الـ repo ديالك
5. اضغط على الـ service → اذهب لـ **Variables**
6. أضف:
   ```
   TELEGRAM_BOT_TOKEN = 7123456789:AABBcc...
   ADMIN_CHAT_ID      = 123456789
   ```
7. اضغط **Deploy** → البوت يخدم 24/7 ✅

### طريقة رفع ZIP مباشرة:
1. اذهب لـ https://railway.app
2. New Project → Deploy from local directory
3. ارفع مجلد المشروع

---

## الخطوة 4️⃣ (بديل) — النشر على Render (مجاني)

1. اذهب لـ https://render.com → Sign up
2. New → **Background Worker**
3. اربط الـ GitHub repo
4. إعدادات:
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `python bot.py`
5. أضف Environment Variables:
   - `TELEGRAM_BOT_TOKEN` = token ديالك
   - `ADMIN_CHAT_ID` = chat id ديالك
6. اضغط **Create Background Worker** ✅

---

## ⚡ الميزات الجديدة في v2.0

| الميزة | التفاصيل |
|--------|----------|
| 👥 Multi-user | أي شخص يكتب /start يتسجل تلقائياً |
| ⚙️ إعدادات شخصية | كل مستخدم يتحكم في تنبيهاته |
| 📊 قاعدة بيانات SQLite | حفظ المستخدمين وتجنب تكرار الأخبار |
| 🔥 تنبيهات HIGH IMPACT | CPI / NFP / FOMC قبل ساعة |
| 🎯 Bias الجلسة | حكم إجمالي Bullish/Bearish/Neutral |
| 🗓 التقويم الاقتصادي | البيانات المهمة هذا الأسبوع |
| 📋 قائمة inline buttons | تجربة مستخدم أفضل بدون كتابة أوامر |
| 📈 إحصائيات Admin | /stats للمشرف فقط |

---

## 🕐 التنبيهات التلقائية

| الوقت (مغرب) | الحدث |
|-------------|-------|
| 07:00 | 🌅 ملخص بداية اليوم |
| كل ساعة :10 | 📰 أخبار جديدة (فقط إذا فيها جديد) |
| 14:30 | ⚡ تنبيه جلسة نيويورك |
| كل 10 دق | 🔍 فحص البيانات الاقتصادية القادمة |

---

## 🛠 الأوامر المتاحة

```
/start    → تسجيل + القائمة الرئيسية
/news     → آخر أخبار XAUUSD والدولار
/analysis → تحليل Bullish/Bearish مع Score
/ny       → تنبيه جلسة نيويورك يدوي
/calendar → التقويم الاقتصادي هذا الأسبوع
/settings → إعدادات التنبيهات الشخصية
/stats    → إحصائيات (للمشرف فقط)
/help     → المساعدة
```

---

## ⚠️ ملاحظات مهمة

- هذا البوت **إرشادي فقط** — مو توصية تداول
- دائماً دير إدارة رأسمال قبل أي صفقة
- الأخبار من مصادر عامة مجانية — للأخبار المتقدمة جرّب Investing.com Premium API

---

## 🆘 مشاكل شائعة

**البوت ما يجاوبش؟**
→ تأكد من الـ TOKEN صحيح في Variables

**ما يوصلش الرسائل التلقائية؟**
→ تأكد من الـ ADMIN_CHAT_ID صحيح، وأنك كتبت /start أول مرة

**خطأ في الـ deploy؟**
→ تأكد أن Procfile موجود وفيه: `worker: python bot.py`
