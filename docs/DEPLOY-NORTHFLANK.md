# النشر على Northflank — دليل خطوة بخطوة

البوت جاهز للنشر على Northflank (Sandbox المجاني): شغال 24/7 من غير نوم،
وقرص دائم فالذاكرة (SQLite) بتفضل بعد أي إعادة تشغيل، وDocker زي ما هو من
غير إعادة كتابة. التكلفة: خدمة `nf-compute-50` بـ 12 دولار/شهر، جوه رصيد
الـ Sandbox المجاني (20 دولار/شهر) — يعني 0 جنيه طالما الخدمة دي بس اللي
شغالة. التفاصيل الكاملة في `docs/research-deploy-hosting-survey.md`.

## قبل ما تبدأ — checklist

- [ ] **بطاقة دفع للتحقق (إجباري):** Northflank بيطلب بطاقة من كل المستخدمين
      عشان ينشئوا أي resource، حتى على الـ Sandbox المجاني — ده من الـ billing
      docs بتاعتهم، مش من صفحة الأسعار (اللي بتقول "no card needed"). البطاقة
      بتتأكد بس، ومش بتتخصم منها حاجة طالما جوه الـ 20 دولار المجاني.
      سيف معندوش Visa دولية — الحلول اللي اتبحثت (التفاصيل في
      `docs/research-payment-cards-egypt.md`): **EverTry** أحسن اختيار (~4 دولار
      مرة واحدة، تمويل بالجنيه عن طريق InstaPay، ~10 دولار / 550 جنيه إجمالي
      يكفي)، بعده RedotPay (~10 دولار، بس تمويله كريبتو)، بعده Pyypl (مجانًا،
      ~10 دولار حد أدنى للشحن)، أو بطاقة دولارية من QNB/CIB (أكيد بس محتاجة
      زيارة فرع + إيداع 100–200 دولار). **بطاقة وهمية/مولّدة مش هتعدي أبدًا:**
      Stripe بيعمل authorization حقيقي مع البنك، والأرقام المختلقة ممكن تتسبب
      في حظر الحساب. لو مفيش بطاقة خالص: البديل اللي من غير بطاقة هو Render
      (الـ free tier مش محتاج بطاقة — شوف `docs/DEPLOY.md`).
- [ ] **GitHub repo موجود:** البوت لسه ملوش git repo أصلًا — لازم يتعمل repo
      (على GitHub) ويترفع عليه الكود من `~/workspace/bahgat-bot/`، فرع `main`،
      والـ Dockerfile في الـ root. دي خطوة مفتوحة، وMuse مش هينشئ أي حساب
      من غير إذن سيف.
- [ ] **المفاتيح الأربعة جاهزة عند سيف** (هو اللي يحطها بنفسه في الـ dashboard
      — مفاتيح الـ Secure Vault بتاعة Muse مش متاحة للسيرفر): التوكن بتاع
      التليجرام، Gemini، Groq، NVIDIA NIM.
- [ ] البوت أخد admin في جروب الاختبار (اتعمل 2026-11-25): id الجروب
      `-1005812444791`.

## الخطوات

### 1. اعمل Project
Northflank dashboard → Create project → سمّيه `bahgat-bot` مثلًا → اختار
region قريب (Frankfurt الأقرب لمصر).

### 2. اعمل Combined service
داخل الـ project → Create service → **Combined service** (build + run في
خدمة واحدة) → سمّيها `bahgat-bot`.

### 3. الـ Build — من GitHub
- Build type: **Build from Git repository** (أو "Git").
- ربط حساب GitHub واختار الـ repo بتاع البوت، فرع **`main`**.
- Build type: **Dockerfile** — الـ Dockerfile في الـ root بتاع الـ repo
  (بيثبّت ffmpeg وكل الـ dependencies، والـ CMD بتاعه exec-form).
- Context: الـ root (`/`). مفيش build args مطلوبة.
- Build triggers: خلّيها على الـ default (build على كل push لـ `main`).

### 4. الـ Compute — أصغر خطة
- Instances: **1** (واحدة بس — اتنين pollers على نفس التوكن بيعملوا
  409 Conflict وبيقسّموا الـ updates بينهم).
- Compute plan: **`nf-compute-50`** — 0.5 vCPU / 1 GB RAM، بـ 12 دولار/شهر
  (جوه الـ 20 دولار المجاني).

### 5. الـ Volume — القرص الدائم (مهم: دي ذاكرة البوت)
- Addons → **Persistent volume** → Size: **1 GB** → Mount path: **`/data`**.
- البوت بيقرا مكان الـ data من الـ env var **`BAHGAT_DATA_DIR`** (جديد في
  النسخة دي — قبل كده كان الـ path متثبّت في الكود على `<project root>/data`
  في 4 أماكن: `brain/memory.py`، `tg/handlers.py`، `brain/router.py`،
  `tg/app.py`). من غير الـ env var دي، الـ volume ملوش لازمة والـ DB
  هتتمسح مع كل redeploy.
- الـ DB والـ heartbeat والـ downloads والـ voice كلهم تحت `/data` لما
  الـ env var يتظبط.

### 6. الـ Networking — افتح بورت الـ health check
- Networking → Add port → Protocol: **HTTP** → Internal port: **8080**.
- البوت بيشغّل health endpoint على `0.0.0.0:$PORT` (افتراضي 8080) — شوف
  الخطوة 7 للـ env var.

### 7. الـ Environment variables — انسخها بإيدك في الـ dashboard
Service → Environment → ضيف كل دول (القيم من عند سيف، مش من Muse):

| المتغير | القيمة | ملحوظة |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | توكن @Bahgoti_bot | إجباري |
| `OWNER_ID` | `1415214630` | إجباري — id سيف |
| `GEMINI_API_KEY` | مفتاح Gemini | |
| `GROQ_API_KEY` | مفتاح Groq | |
| `NVIDIA_API_KEY` | مفتاح NVIDIA NIM | |
| `ALLOWED_CHAT_IDS` | `-1005812444791` | البوت يرد في جروب الاختبار بس |
| `BAHGAT_DATA_DIR` | `/data` | الـ DB على الـ volume الدائم |
| `DROP_PENDING_UPDATES` | `false` | شوف تحت — مهم |
| `PORT` | `8080` | بورت الـ health endpoint |
| `LOG_LEVEL` | `INFO` | اختياري |

- **متحطش أي مفتاح في الـ repo أو الـ Dockerfile أو الـ render.yaml** —
  الـ dashboard بس. لو مفتاح اتسرب في git، لازم يتلغي ويتجدد فورًا
  (BotFather للتوكن، وconsoles بتاعة Groq/Gemini/NVIDIA للمفاتيح).
- **متحطش `CEREBRAS_API_KEY` ولا `OPENROUTER_API_KEY`:** سيف قال "طنشهم
  دلوقتي" (2026-11-25) — البوت بيشتغل من غيرهم عادي.
- **`DROP_PENDING_UPDATES=false` ليه؟** الافتراضي في الكود `true` (بعد أي
  downtime البوت بيرمي الرسايل القديمة عشان ميردش على كلام من امبارح
  ويحرق quota). على Northflank إعادة التشغيل نادرة، بس لو حصلت، الـ `false`
  بتخلي تليجرام يبعت الرسايل اللي اتبعتت والبوت نايم (بيحتفظ بيها 24 ساعة)
  بدل ما تضيع. مكان الإعداد: `core/config.py` (field `drop_pending_updates`،
  بيتقرا من الـ env)، وبيتطبق في `main.py` في `app.run_polling(...)`.

### 8. الـ Health check
- Health checks → Path: **`/healthz`** (وفيه alias `/health`).
- الـ endpoint بيرجع `200 {"status":"ok","last_poll_age_seconds":N}` لما
  الـ polling loop حي (آخر heartbeat من أقل من 300 ثانية)، و`503` لو
  الـ heartbeat قديم أو مش موجود. الـ heartbeat بيتكتب في
  `/data/heartbeat.json` كل 60 ثانية من `tg/app.py`.
- Initial delay / grace period: **60 ثانية** على الأقل (أول heartbeat
  بيتكتب بعد الـ startup مباشرة، بس سيب هامش).
- الـ Dockerfile فيه `HEALTHCHECK` بيقرا نفس ملف الـ heartbeat — دي للـ
  Docker نفسه، وNorthflank بيستخدم `/healthz`.

### 9. Deploy
- اضغط Deploy / Run. أول build هياخد كام دقيقة (تثبيت ffmpeg + الـ deps).
- راقب الـ logs: لازم تشوف `health server listening on 0.0.0.0:8080`
  و`Bahgat starting — polling`، ومفيش exception.

## الاختبار الحي (في جروب الاختبار `-1005812444791`)
- `بهجت عامل ايه` — لازم يرد.
- `بهجت ايه سعر الدولار النهارده` — لازم يدور على النت ويرد بمصدر.
- `بهجت انت حمار` — لازم يتعصب (mood) مش يضحك.
- `/stats` (من سيف بس) — لازم يطلع الـ pool والـ fair share.
- بعد الـ deploy، اعمل restart للـ service من الـ dashboard وتأكد إن
  البوت لسه فاكر اللي حصل قبلها (الذاكرة على الـ volume).

## لو حصلت مشكلة
- الـ service مش بيبدأ: شوف الـ logs — غالبًا env var ناقص
  (`TELEGRAM_BOT_TOKEN` أو `OWNER_ID` بيرموا `RuntimeError` عند الـ startup).
- `/healthz` بيرجع 503 على طول: الـ polling loop ميت — شوف الـ logs
  (توكن غلط؟ تليجرام مش واصل؟).
- البوت بيرد وبعدين بينسى كل حاجة بعد redeploy: الـ volume مش mounted
  على `/data` أو `BAHGAT_DATA_DIR` مش متظبط على `/data` — اتأكد من الاتنين.
- 409 Conflict في الـ logs: فيه instance تانية شغالة بنفس التوكن
  (local test + الـ deployed) — وقّف الـ local فورًا.

## لو Northflank طلب بطاقة ومفيش حل
البديل الجاهز: Render free web service (من غير بطاقة) — شوف `docs/DEPLOY.md`
والـ stack الكامل (pinger + Turso + R2 backup) في
`docs/research-deploy-state-persistence.md`. وأوراكل VPS هو البيت الدائم
الأفضل على المدى الطويل (شوف `docs/research-deploy-hosting-survey.md`).
