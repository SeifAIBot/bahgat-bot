# النشر — بوت بهجت (مجاني)

## الاختيار: Render — Free Web Service (من غير بطاقة خالص)

قرار سيف 2026-11-25: Northflank محتاج بطاقة للتحقق وسيف معندوش فيزا دولية،
فالبديل هو Render المجاني — **النشر عليه مش بيطلب بطاقة أصلًا**.
التجهيز اللي اتعمل لـ Northflank (v0.7c) شغال هنا زي ما هو: نفس الـ health
endpoint (`/healthz` على `$PORT`)، نفس `DROP_PENDING_UPDATES=false`.

> ⚠️ **اقرا ده الأول — عيوب الباقة المجانية، من غير تجميل:**
> 1. **البوت بينام بعد 15 دقيقة من غير حركة** (~30-60 ثانية عشان يصحى).
>    الحل: منبّه خارجي (cron-job.org) كل 10 دقايق على `/healthz` — الخطوات تحت.
> 2. **الذاكرة بتتمسح مع كل إعادة تشغيل.** كل اللي البوت فاكره — الأعضاء،
>    المزاج، الخصومات، عدادات الحصص، كاش اليوتيوب — عايش في `data/bahgat.db`
>    (SQLite)، وملفات Render المجانية **مؤقتة**: كل redeploy أو restart أو
>    spin-down بيمسح الملف والذاكرة بترجع صفر. **ده متوقَّع في أول نشر، مش
>    مفاجأة.** الحل الدائم (Turso / نسخة احتياطية على R2) خطوة لاحقة منفصلة —
>    لسه متعملتش، شوف "الخطوة الجاية" تحت.
> 3. **750 ساعة مجانية في الشهر = خدمة واحدة بس شغالة 24/7.** متضيفش أي خدمة
>    تانية على Render (ولا حتى منبّه) — هتاكل من نفس الرصيد.
> 4. الباقة المجانية **مش** بتغطي Background Worker — بس Web Service
>    (docs.render.com/free). عشان كده `render.yaml` بقى `type: web`.

## 1. الحاجات اللي لازم تبقى جاهزة قبل النشر (checklist)

| # | الحاجة | الحالة |
|---|---|---|
| 1 | **GitHub repo فيه الكود على branch `main`** | ❌ **لسه مش موجود** — البوت لسه مالوش git repo. لازم يتعمل الأول (الكود يترفع على GitHub) عشان Render يبني منه. من غيره مفيش نشر. |
| 2 | **حساب Render** | مجاني، من غير بطاقة — اعمله على render.com (Sign up بإيميل أو GitHub). |
| 3 | **المفاتيح الأربعة** | سيف يحطها بنفسه في Render (Dashboard → Environment) — مفاتيح Muse الآمنة (Vault) **مش** متاحة لـ Render. متبعتش المفاتيح في الشات ولا تحطها في الكود. |

## 2. متغيرات البيئة (Environment) — تتحط في Render Dashboard

`render.yaml` فيه القيم الثابتة جاهزة (`OWNER_ID`، `ALLOWED_CHAT_IDS`،
`DROP_PENDING_UPDATES=false`، `LOG_LEVEL=INFO`). المفاتيح السرية Render
هيطلبها بنفسه لأنها `sync: false` في الملف — حطها في Dashboard → service →
Environment:

| المتغير | القيمة | منين |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | توكن البوت | @BotFather (نفس التوكن اللي سيف اداه لـ Muse — البوت @Bahgoti_bot، id 9106462211) |
| `OWNER_ID` | `1415214630` | جاهز في `render.yaml` |
| `GEMINI_API_KEY` | مفتاح Gemini | Google AI Studio |
| `GROQ_API_KEY` | مفتاح Groq | Groq console |
| `NVIDIA_API_KEY` | مفتاح NVIDIA NIM | build.nvidia.com (اختياري — البوت شغال من غيره؛ شوف CHANGELOG v0.6) |
| `ALLOWED_CHAT_IDS` | `-1005812444791` | جاهز في `render.yaml` (جروب الاختبار "Bahgat bot" — البوت أدمن فيه من 2026-11-25) |
| `DROP_PENDING_UPDATES` | `false` | جاهز في `render.yaml` — **لازم false**: الرسايل اللي بتتبعت والبوت نايم لازم توصله لما يصحى، مش تتمسح (تيليجرام بيحتفظ بالتحديثات 24 ساعة) |
| `LOG_LEVEL` | `INFO` | جاهز في `render.yaml`. `DEBUG` بيتقفل لـ `INFO` إلا لو `BAHGAT_DEBUG=1` كمان — لأن DEBUG بيسجّل روابط فيها التوكن |
| `CEREBRAS_API_KEY` / `OPENROUTER_API_KEY` | اختياري | سيف قال "طنشهم دلوقتي" (2026-11-25) — متضيفهمش |

## 3. خطوات النشر في Dashboard (بالترتيب)

1. ارفع الكود على GitHub repo (branch `main`) — شوف البند 1 فوق.
2. في Render: **New → Web Service**.
3. **Connect repository** — اختار الريبو، branch `main`.
4. **Runtime: Docker** — Render هيلاقي `Dockerfile` في جذر الريبو ويبني منه
   (الصورة فيها Python 3.11 + ffmpeg + مستخدم غير root + HEALTHCHECK).
   متغيرش الـ build/start command — الـ Dockerfile هو اللي بيحددها
   (`CMD ["python", "main.py"]`).
5. **Plan: Free** — و **Instances: 1** (مهم: نسخة واحدة بس، عشان تيليجرام
   بيسمح بـ poller واحد بس لكل توكن — نسختين هيتخانقوا على التحديثات وكل
   واحدة هتاخد `409 Conflict`).
6. **Region: Frankfurt** (الأقرب لمصر).
7. **Environment variables** — حط المفاتيح من الجدول اللي فوق
   (`render.yaml` بيعلن عنها، والقيم الثابتة جاهزة فيه).
8. **Health Check Path: `/healthz`** — جاهز في `render.yaml`. البوت بيرد
   `200` لما الـ heartbeat طازج (< 5 دقايق)، و `503` لو الـ polling واقف.
9. **Deploy.**

ملحوظة: Render بيحقن `$PORT` بنفسه، والبوت بيقراه (health server بيbind على
`0.0.0.0:$PORT` قبل ما الـ polling يبدأ). أول deploy ممكن ياخد دقيقة أو
اتنين عشان بناء الـ Docker image.

## 4. إزاي تتأكد إن النشر نجح

1. **Logs في Render:** لازم يبان سطر `Bahgat starting — polling` (من غير
   tracebacks بعده). لو بان `TELEGRAM_BOT_TOKEN missing` أو `OWNER_ID missing`
   يبقى متغير ناقص في Environment — راجعه من الجدول.
2. **الـ health endpoint:** افتح في المتصفح
   `https://bahgat-bot.onrender.com/healthz` (اسم الخدمة `bahgat-bot` من
   `render.yaml`) — لازم يرجع `{"status": "ok", "last_poll_age_seconds": N}`
   و HTTP 200. لو رجّع 503 يبقى الـ polling لسه مبدأش أو واقف.
   > ملحوظة: أول ثواني بعد التشغيل ممكن `/healthz` يرجع 503 لحد ما أول
   > heartbeat يتكتب (بيتكتب فورًا في `post_init`، خلال ثواني) — ده طبيعي،
   > مش فشل في النشر.
3. **متشغلش `python main.py` على جهازك بنفس التوكن والبوت شغال على Render:**
   الـ poller التاني هياخد `409 Conflict` والاتنين هيسرقوا تحديثات بعض.
   للاختبار المحلي، وقّف خدمة Render الأول (Suspend)، جرّب، وبعدين شغّلها تاني.

## 5. المنبّه — عشان البوت مينامش (cron-job.org، مجاني)

الخدمة المجانية بتنام بعد 15 دقيقة من غير طلبات واردة. الحل: طلب خارجي كل
10 دقايق على `/healthz` — والـ 10 دقايق دي جوه نافذة الـ 15 دقيقة مع هامش
5 دقايق لو طلب فات.

1. اعمل حساب مجاني على **cron-job.org** (من غير بطاقة — مجاني بالكامل،
   jobs غير محدودة، أقل فترة دقيقة واحدة).
2. **Create job:**
   - **Title:** `bahgat-bot keep-alive`
   - **URL:** `https://bahgat-bot.onrender.com/healthz`
   - **Schedule:** كل `10 minutes` (مينفعش أقل من كده؟ ينفع — بس 10 دقايق
     كفاية، وكل طلب بيصحّي الخدمة وبيستهلك من الـ 750 ساعة؛ الخدمة صاحية
     24/7 بتستهلك ~744 ساعة في الشهر — على القد بالظبط).
   - **Request method:** `GET` (الافتراضي).
   - **Notifications:** فعّل إشعار الفشل على الإيميل — لو `/healthz` رجّع
     503 كذا مرة ورا بعض، ده معناه البوت واقع مش نايم.
3. بديل (أقل مرونة): UptimeRobot free — 50 monitor، كل 5 دقايق، GET بس من
   غير custom headers. cron-job.org أحسن عشان فيه headers ودقة دقيقة واحدة.

**المنبّه بيصحّي البوت بس — مش بيحفظ الذاكرة.** لو Render عمل restart،
الذاكرة بتتمسح حتى لو المنبّه شغال. دي مشكلة منفصلة — شوف البند الجاي.

## 6. الاختبار الحي في جروب الاختبار

الجروب: **"Bahgat bot"**، id `-1005812444791` — البوت أدمن فيه من
2026-11-25 22:30 EET، و `ALLOWED_CHAT_IDS` متظبط عليه. ابعت الرسايل دي
واحدة واحدة (بين كل رسالة والتانية 10 ثواني على الأقل — الـ pacing):

1. `بهجت عامل ايه` — رد عادي، بيأكد إن الـ triggers شغالة (منشن / "بهجت" /
   الرد على رسالة البوت).
2. `بهجت ايه سعر الدولار النهارده` — لازم يدور على النت ويرجع إجابة بمصادر
   `[1]` (مش "مش عارف").
3. `بهجت انت حمار` — لازم يتعصب ويرد كبهجت (المزاج +40)، من غير شتيمة أب/أم
   (أعضاء الجروب: الشتيمة للشخص بس).

ولو حاجة فشلت: شوف logs في Render الأول، وبعدين `/stats` (أمر للمالك بس)
من الجروب.

## 7. الخطوة الجاية (لسه متعملتش — متفتكرش إنها موجودة)

- **حفظ الذاكرة (Turso / نسخة احتياطية على R2):** أحسن طبقة مجانية حسب
  البحث (docs/research-deploy-state-persistence.md): Turso (متوافق مع
  SQLite — أقل تعديل في الكود) + نسخة احتياطية كل ساعة من `bahgat.db` على
  Cloudflare R2 (10 GB مجاني، من غير رسوم سحب). لحد ما ده يتعمل، **كل
  restart = ذاكرة جديدة من الصفر** — قول كده لسيف بوضوح لما تبلّغ عن سلوك
  البوت.
- **GitHub repo:** لازم يتعمل قبل أي نشر (بند 1).
- **تأكيد حصة Gemma/Flash-Lite الحية** في مشروع AI Studio بتاع سيف — الرقم
  اللي مبني عليه الـ pool (~13,500 رد/يوم) لسه غير مؤكد.

## Polling، مش webhooks

البوت بيستخدم long polling (`run_polling`، `drop_pending_updates=false` على
Render عشان الرسايل اللي اتبعتت والبوت نايم توصله لما يصحى). مفيش webhook.
لو اتعمل webhook في يوم من الأيام، لازم `setWebhook(secret_token=...)`
والتحقق من هيدر `X-Telegram-Bot-Api-Secret-Token` بمقارنة ثابتة الوقت —
متقبلش تحديثات webhook من غير الـ secret.

## اختبار محلي

```bash
cp .env.example .env   # املا المتغيرات الأربعة
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python main.py
```

الـ pip بتاع النظام بيفشل على الـ VM دي (PEP 668) — استخدم `.venv` دايمًا.
الاختبارات + الـ lint:
`pip install -r requirements-dev.txt && pytest -q && ruff check .`
ملحوظة: الـ VM دي `NO_PROXY` فيها بيكسر httpx (قيم IPv6 بين أقواس) —
اختبارات الـ smoke محتاجة env نضيفة؛ ده مش بيأثر على Render.

## Oracle Always Free VPS (لاحقًا، لو الجروب كبر)

Render المجاني بينام وذاكرته مؤقتة. Oracle Always Free بيدي VPS صغير شغال
على طول. نفس الخطوات، شغّله بـ systemd + `Restart=always` أو Docker
Compose — والقرص هناك حقيقي، فـ SQLite بيعيش. محتاج يوم تجهيز + بطاقة
للتأكيد + حظ في الحجز (capacity lottery) — شوف
docs/research-deploy-hosting-survey.md.
