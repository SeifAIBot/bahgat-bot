# Changelog
## 2026-11-26 — v0.7e Cloady deploy + search follow-up fix (deploy target: Cloady, no card)
- **Deploy moved Render → Cloady.** Render's "Add Card" modal blocked the
  free deploy on Seif's brand-new account (account-level anti-fraud check;
  Render's docs say no card, but the check fires anyway and no config
  bypasses it). Cloady free workspace (0.5 vCPU / 1 GB RAM / 5 GB SSD,
  Germany EU1, no card, no expiry) now hosts the bot; deploy went LIVE
  2026-11-26 02:03 EET and the bot replied in the test group 02:10 EET.
- `docker-compose.yml`: bind mount `./data:/app/data` rejected by Cloady
  ("volumes must mount a declared named volume") — now a declared named
  volume `bahgat-data:/app/data` (also the persistence layer: memory
  survives redeploys, unlike Render free). `env_file: .env` dropped (the
  platform injects env vars; a missing .env would fail the parse),
  `cpus: 1.0` → `0.5` to stay inside the free tier. `ALLOWED_CHAT_IDS`
  deliberately left unset in Cloady per Seif's call — the bot answers in
  any group it is added to.
- **Search follow-up fix (`tg/handlers.py`, `_search_query`).** Live bug:
  Seif asked about the Waraq incident, then "ايه الحصل" — the bot
  searched the literal follow-up and answered with song lyrics about
  "عمره ما غنى ولا عرف الهوى". Short follow-ups (<= 4 words) now inherit
  the most recent substantive user turn from history, so the query keeps
  the topic. Both search call sites (search intent + unknown-retry loop)
  use it. Tests: `tests/test_search_followup_v07e.py` (5 tests).
- **Intent keywords (`brain/intent.py`).** Two more live misses from the
  same session: "ايه الحصل" (without اللي) did not match `_SEARCH_WORDS`
  (only "ايه اللي حصل" was there), so follow-ups fell to just_chat and
  only got searched via the unknown loop; "عايز اغنيه" did not match
  `_YOUTUBE_WORDS`, so a song request never offered the video/audio
  choice. Added "ايه الحصل"/"ايه حصل" to search words and
  "عايز اغنيه"/"عاوز اغنيه"/"عايز فيديو"/"عاوز فيديو" to YouTube words.
  Tests in `tests/test_intent.py`.
- Test fix: `test_gemini_skipped_when_daily_requests_at_cap` seeded usage
  by UTC date while the router keys Gemini by Pacific date — it passed at
  23:44 UTC and failed at 00:18 UTC the same night. Now seeds by Pacific
  date, like the router.
- 268 tests pass (263 + 5 new), py_compile + ruff clean.

## 2026-11-25 — v0.7d Render free web service conversion (deploy target: Render, no card)
- `render.yaml` converted from Background Worker to **free Web Service**:
  `type: web`, `plan: free`, `numInstances: 1`, `env: docker` (Dockerfile
  runtime — the image carries ffmpeg, which the native Python env lacks),
  `region: frankfurt`, `dockerfilePath: ./Dockerfile`,
  `healthCheckPath: /healthz`. Render Free does NOT cover workers
  (docs.render.com/free), so the old worker config could never deploy free.
- `DROP_PENDING_UPDATES=false` is now a literal env var in `render.yaml`
  (messages sent while the bot slept are delivered on wake — Telegram
  holds updates 24h — instead of discarded). Secrets stay out of the file:
  `TELEGRAM_BOT_TOKEN` / `GEMINI_API_KEY` / `GROQ_API_KEY` /
  `NVIDIA_API_KEY` are declared with `sync: false`, so Render asks for them
  in the dashboard; `OWNER_ID=1415214630`,
  `ALLOWED_CHAT_IDS=-1005812444791`, `LOG_LEVEL=INFO` are literal values.
- Verified the $PORT path end to end: `main.py` starts the v0.7c health
  server (tg/health.py) BEFORE `run_polling`, so the Docker CMD
  `["python", "main.py"]` binds `0.0.0.0:$PORT` at boot; the heartbeat file
  is first written in `post_init`, so `/healthz` turns 200 within seconds
  of startup (brief 503 in the first seconds is normal — documented in
  DEPLOY.md). `resolve_port()` reads Render-injected `$PORT`, default 8080.
  No code change was needed for the port; only a `main.py` comment now
  names Render free alongside Northflank.
- `docs/DEPLOY.md` rewritten as a complete Render deploy checklist in
  Egyptian Arabic: free-tier trade-offs stated plainly (sleeps after 15 min
  idle; SQLite wiped on every redeploy/restart — memory loss is EXPECTED on
  this first deploy; 750 free hours/month = exactly one service 24/7),
  prerequisites, exact env-var table, dashboard steps (New → Web Service →
  Docker → Free → 1 instance), verification (logs + GET /healthz),
  cron-job.org pinger setup (every 10 min, free, 1-min granularity — better
  than UptimeRobot's 5-min GET-only), live-test messages for the test group
  (-1005812444791), and the next step flagged, NOT built: Turso/R2
  persistence (docs/research-deploy-state-persistence.md).
- Tests: **263 pass in .venv, py_compile clean, ruff clean.** Smoke tests:
  health server binds `$PORT` in a subprocess (`/healthz` 200 fresh,
  `/health` alias 200, 503 stale); `import main` + `build_application()`
  builds 6 handlers; `DROP_PENDING_UPDATES=false` parses to False.
  Docker image build NOT verified — docker is not installed in this VM.
- Open blockers (not done here): (1) no GitHub repo exists yet — Render
  builds from a GitHub repo on branch main; (2) no Render account yet
  (free, no card); (3) Seif must paste his 4 keys into the Render
  dashboard himself (Vault keys are not available to Render). Nothing was
  deployed; no account created; no credentials touched.

## 2026-11-25 — v0.1 scaffold
- Modular scaffold: config-driven persona/providers/rules, plugins, multi-LLM router stub, SQLite memory schema, Docker.
- Training video lists compiled (voice vs style). Audio cleanliness NOT verified yet.
- Waiting: Telegram bot token (secure link sent), owner ID, test group.

## 2026-11-25 — v0.2 core + tools (no token yet, untested live)
- Brain router: Gemini -> Groq -> OpenRouter, OpenAI-compatible, auto-fallback on error.
- Memory: SQLite per-member (mood, grudge, notes), recent 12 messages context.
- Mood: insult +40, praise -20, voice when asked / mood>=90 / random 12%.
- Intent from normal talk (no slash commands): search / youtube / voice / just_chat.
- Tools: DuckDuckGo search + page fetch, yt-dlp 480p / mp3 with 50 MB limit, Edge TTS ar-EG-ShakirNeural -> ogg voice note.
- Handlers: reply only on mention / "بهجت" / reply-to-bot, owner-only control phrases for Seif.
- Tests: insult rules + mood + intent pass locally (pytest not installed, run via python -c).
- Still blocked: Telegram token, owner ID, test group, Gemini/Groq keys — needed for live test + deploy.

## 2026-11-25 — Telegram connected, bot verified
- Token submitted via secure link and verified with getMe: @Bahgoti_bot, id 9106462211, first name بهجت.
- Connector doc + helper at ~/workspace/custom-connectors/custom.telegram/ (getMe / getUpdates / sendMessage).
- getUpdates empty — bot not in any group yet.
- Known: can_read_all_group_messages is false, so bot must be admin in test group (or privacy disabled in BotFather) to see plain "بهجت" messages.
- Still waiting: owner ID, test group link, Gemini/Groq keys.

## 2026-11-25 — Gemini connected and verified
- Gemini key submitted, models list works via OpenAI-compatible endpoint.
- gemini-3-flash-preview generates replies (verified). Primary model updated to it.
- gemini-2.5-flash/pro retired (404), gemini-3.1-pro-preview free-tier quota 0 (429).
- Still waiting: Groq key, adding @Bahgoti_bot as admin to test group.

## 2026-11-25 — Groq connected and verified
- Groq key submitted, models list works, openai/gpt-oss-120b generates Egyptian Arabic replies.
- Groq needs a browser User-Agent header, otherwise Cloudflare returns 403 error 1010.
- Brain is now complete: Gemini (gemini-3-flash-preview) primary, Groq (gpt-oss-120b) fallback.
- Still waiting: adding @Bahgoti_bot as admin to the test group, then live test + deploy.

## 2026-11-25 — v0.3 code review + brain hardening (P0, from professional research)
- Router v3: classified retries (only 408/429/5xx), exponential backoff + full jitter, honour Retry-After, circuit breaker (3 failures -> OPEN 60s), SQLite quota table (skip exhausted provider until midnight UTC), token counting, simple->Groq first / hard->Gemini first, temperature per intent (search 0.25, chat 0.85).
- Prompt v3: dynamic system prompt assembly (role, objective, constraints early, memory/mood/search/style, few-shot escape hatch), user text wrapped in <user_message> tags, guardrails in code not prompt.
- Verification in code: family-insult enforcement for members, banned AI phrases, HTML escaping, 4096-char split on sentence boundaries.
- Telegram reliability: dedup on update_id (INSERT OR IGNORE first), per-chat rate limit (1 msg/s, 20/min/group), YouTube video/audio inline buttons (yt:video / yt:audio) instead of pretending to download, callback answers.
- Memory schema: processed_updates, provider_usage, pinned_facts, outbox tables.
- Added .gitignore (.env, data/, *.db), tenacity in requirements (documented, hand-rolled retry kept for now).
- Tests: verify, prompt, router circuit breaker — all pass locally.
- Still open (from research, P1/P2, not yet built): LLM tool-calling replacing keyword intent, structured BotPlan, LLM-as-judge for search answers only, RAG over Bahgat transcripts for style, rolling summarisation, /stats owner command, CI with ruff/mypy.

## 2026-11-25 — v0.4 code review fixes (C1-C11, M1-M12)
- Router v4: max_completion_tokens=4000, reasoning_effort=low (Groq), thinking low (Gemini), temp 0.7 chat / 0.25 search, one client per provider + close() on shutdown, no raw exception leak to group (log only).
- Search: resolve DDG uddg redirects, raise_for_status, content-type check, Lite fallback, realistic UA.
- Search-when-unknown loop: if reply says "مش عارف" and no search ran, search once and retry with results.
- YouTube: inline video/audio buttons now actually download in to_thread, per-request UUID folder, --no-playlist --max-filesize 50M, capture real filepath, delete after send.
- Insult enforcement: post-filter in code, plus owner commands normalised and checked before trigger gate, mute/clear-memory owner commands.
- Memory/mood: history fetched BEFORE inserting current message, assistant stored with bot id, mood time-decay -10/hour, prune messages to last 200/chat, index on messages(chat_id,id).
- Blocking work: yt-dlp in to_thread, voice split at sentence boundaries, file handles closed, files deleted.
- Config: persona.yaml + examples.md now loaded at startup, OpenRouter removed (no key, never ran), providers.yaml honoured, render.yaml (Background Worker) + docs/DEPLOY.md + .dockerignore added.
- Tests: 17 tests pass in .venv (verify, prompt, router, intent, insult rules). System pip install fails (PEP 668) — use .venv, documented in DEPLOY.md.
- Still open (P1/P2, not built yet): LLM tool-calling replacing keyword intent, structured BotPlan, LLM-as-judge for search only, RAG over Bahgat transcripts, rolling summarisation, /stats owner command, CI ruff/mypy.

## 2026-11-25 — v0.4b search fix (live verified)
- Search rewritten from httpx to urllib: httpx mis-parses NO_PROXY in this VM and fails SSL through the egress proxy. Live test now returns 5 results with real URLs (not DDG redirects) and fetches pages.
- Split-message hard-split fix: long single sentences now split at 4000 chars (test was failing).

## 2026-11-25 — v0.5 review rounds 2–6 (five independent reviews, deduplicated)
Five independent review rounds were run against v0.4 and their overlapping findings
deduplicated; v0.5 implements the highest-priority fixes. **127 tests pass in .venv
(pytest tests/ -q), py_compile clean, ruff check passes. `import main` + `build_application()`
verified (6 handlers).**

### Fixed — security (round 2)
- SSRF in search: `validate_url()` — https only, hostname resolved and rejected if
  private/loopback/link-local (169.254/10/172.16/192.168/::1/fc00), redirects re-validated
  (max 3), body capped ~1 MB. Note: `ipaddress.is_private` is NOT used — in this VM the
  egress proxy returns 198.18.0.0/15 for ordinary public hosts, which it flags.
- yt-dlp argument injection: host allowlist {youtube.com, www.youtube.com, youtu.be,
  music.youtube.com}, leading `-` rejected, `--` inserted before the URL, yt-dlp pinned
  `>=2026.7.4`. Plain text is resolved via code-built `ytsearch1:` first, never passed raw.
- Prompt injection layers: sandwich guardrail after the user message, search results
  labelled untrusted data with `[n]` citations required, grudge/notes never in the system
  prompt (moved to a user-role `[MEMORY]` block, instruction patterns stripped at write
  time), output filter for system-prompt/owner-id/key leakage in `verify.py`.
- Group allowlist `ALLOWED_CHAT_IDS` (env, comma-separated; empty = allow all + startup
  warning, because the test group's numeric chat id is not known yet — only the invite
  link is). Checked before any LLM/search/voice call.
- Real insult-target resolution via `get_chat_member` + `insult_level()` wired into prompt
  AND verify; target == owner (1415214630) is never insulted.

### Fixed — quotas / cost (rounds 2, 5, 6)
- Durable SQLite per-user-per-group daily budget: 30/user/day, 150/group/day, checked
  before LLM/search/voice.
- Groq TPM-429 (ban for Retry-After only) vs TPD-429 (ban to midnight UTC) distinguished;
  Groq-first routing for everything with Gemini reserved (hard cap 15 Gemini req/day,
  stopped before 429); `openai/gpt-oss-20b` added for simple chat.
- Per-chat in-flight lock (one LLM call per chat); typing renewed every 4s; output cap
  400–600 tokens for chat (600 search), Groq `max_completion_tokens` 1500–2000, Gemini 4000,
  `include_reasoning=False` for Groq, `reasoning_effort="low"` both providers.
- Token estimate fixed to `len//2` (len//3 undercounted Arabic ~2x).

### Fixed — brain (round 3)
- Arabic normalisation in intent (diacritics stripped, أ/إ/آ→ا, ة→ه, ى→ي); verb patterns
  (مين كسب/كسب مين/كام/امتى/فين/بكام, هاتلي/هاتيلي/جبلي/شغلي) and insult patterns
  (انت حمار/غبي/كلب/عبيط); `looks_like_praise` implemented (was hardcoded False).
- Real few-shot examples: `persona/bahgat/examples.md` now has 7 real User/Bahgat exchange
  pairs (person-only insult, correct deflection, search answer with [1] citation, praise,
  song request); `persona.yaml` is now wired into `build_system_prompt` (was dead config).
- Grounding v2: top 3 results fetched in parallel, youtube/tiktok skipped for facts, best 2
  kept with URLs, `[n]` citations required, unknown markers widened, in-character
  deflection when still ungrounded.
- Speaker-tagged history (`[name]: text`); single mood-decay mechanism (time-based on read,
  persisted — per-message −5 removed); one canonical `FAMILY_WORDS` list shared by
  `core/rules.py` and `brain/verify.py` with hamza normalisation; `check_reply` rewrites
  silently instead of appending meta-commentary naming the owner/rule.

### Fixed — YouTube / voice (rounds 2, 5, 6)
- Callback state keyed (chat_id, message_id, requester_id), TTL 10 min, non-requester clicks
  rejected, buttons disabled after first click, callback ids deduped, Semaphore(1) per group,
  non-URL query resolved via `ytsearch1:` with title/duration/size shown before download,
  `youtube_files` file_id cache so repeats re-send by file_id.
- Voice: random 12% → 5% only if reply <200 chars, never forced on mood>=90, cap 1/user/5min,
  ffmpeg via `asyncio.to_thread`, Edge TTS timeout 15s, text sent before voice.

### Fixed — reliability / ops (rounds 2, 4, 5, 6)
- `run_polling(timeout=30, allowed_updates=["message","callback_query","chat_member",
  "my_chat_member"], drop_pending_updates=True, bootstrap_retries=-1)`.
- Schema created once at startup (`init_db()`), `processed_updates` pruned >48h, startup disk
  sweeper for `data/downloads` + `data/voice` >1h.
- Telegram `RetryAfter` caught explicitly (sleep `retry_after`, retry once, never send a
  generic fallback on rate limit); structured JSON log line per LLM call (provider, model,
  latency, tokens in/out, reasoning, finish_reason, retries, status); owner-only `/stats`
  (provider usage today, remaining estimates, per-user counts).
- `setMyDescription`/`setMyShortDescription` parody text at startup from `rules.yaml`;
  `my_chat_member` handler (parody+privacy note on add, purge chat data on remove);
  owner-only `/reload` for persona/examples/rules (provider changes still need restart —
  `router.reload_config()` does not exist).
- `.gitignore` now ignores `.venv/`; `requirements-dev.txt` split out (pytest, pytest-asyncio,
  ruff); yt-dlp pinned; unused tenacity/google-genai/httpx removed; `providers.yaml`
  timeout/retries/log_level honoured (or the fields documented); Dockerfile non-root `USER app`
  + HEALTHCHECK (heartbeat file) + `PYTHONUNBUFFERED=1`; `render.yaml` `numInstances: 1`.
- Docs drift fixed: README OpenRouter line, status, and `/reload`/member-list claims now true;
  ARCHITECTURE.md rewritten short and true (plugins marked aspirational/stub, pinned_facts/
  outbox marked dead tables); DEPLOY.md gains ALLOWED_CHAT_IDS, Render Free SQLite-wipe
  warning, single-instance warning, webhook-secret note; `.env.example` cleaned
  (OPENROUTER_API_KEY / RENDER_EXTERNAL_URL removed, ALLOWED_CHAT_IDS added).
- **Pre-existing blocker found and fixed during v0.5:** the local `telegram/` package
  shadowed the installed python-telegram-bot library, so v0.4 could never have run as-is
  (`ImportError: cannot import name 'InlineKeyboardButton'`). Local package renamed to
  `tg/`; `from telegram import …` now always means the installed library.

### Deferred (explicitly NOT built in v0.5, with reason)
- Full RAG over Bahgat transcripts — needs audio download + Whisper transcription + manual
  cleanup (~1 day); keyword/prompt/grounding fixes were worth more first; do after live test.
- Voice-clone training (RVC/GPT-SoVITS) — needs Seif's explicit go/no-go on deepfake risk
  (impersonation/right-of-publicity); flagged, NOT trained.
- LLM-as-judge for search answers — useful but second-order once citations + grounding v2 exist.
- Structured BotPlan via LLM classifier — keyword intent + the v0.5 fixes are sufficient for v1;
  revisit if intent misses persist in live testing.
- Postgres migration — Render Free wipes SQLite on redeploy/restart; documented in DEPLOY.md
  (Neon free Postgres / Oracle Always Free VPS path + startup DB backup note) instead of
  migrating now, before the first live test proves the bot works.
- Full plugin-system rewrite — plugins/ stays a stub; service-layer extraction likewise deferred.
- PTB v22 upgrade — evaluated only: the venv already has PTB 22.8 and tests pass with it
  (`filters.ChatType.GROUPS` works on 21.x and 22.x); requirements still pin 21.11.1, upgrade
  is a one-line decision for deploy time.
- CI workflow — DONE after all: `.github/workflows/ci.yml` (ruff + pytest) was added in v0.5.

### Still blocks the live group test
- Seif must add @Bahgoti_bot as admin to the test group
  (https://t.me/+RN2Fksh8-KU3NWI0) so plain "بهجت" messages are delivered
  (can_read_all_group_messages is false).
- Seif must confirm the test group's numeric chat id so `ALLOWED_CHAT_IDS` can be set
  (currently empty = allow all, with a startup warning).
- Seif must paste the same three keys (Telegram token, Gemini, Groq) into Render env vars
  himself — Muse's Secure Vault keys are NOT available to Render.
- Unverified in this VM: real yt-dlp download/resolve (yt-dlp not installed here — only
  mocked), real Edge TTS + ffmpeg voice (edge_tts not installed here), live LLM calls
  against the new caps, `get_chat_member` with a username string, heartbeat/HEALTHCHECK
  observed live. The VM's `NO_PROXY` env breaks httpx (bracketed IPv6 entries) — smoke
  tests need a clean env; does not affect Render.

## 2026-11-25 — v0.7 fair-share quota core (brain/memory.py only)
Dynamic quota: the fixed caps are gone (100/user/day, 1500/group/day,
owner exemption — all retired, with `USER_DAILY_LIMIT` /
`GROUP_DAILY_LIMIT`, `group_pool_remaining()`, and the "user daily
limit reached" reason). Capacity C is now computed live from provider
budgets (`compute_pool_remaining`: per entry replies = min(RPD left,
TPD left / avg tokens per reply), pool = sum x 0.8 planning haircut)
and divided among the ACTIVE users by weighted max-min fair sharing
(docs/research-quota-fairshare.md, docs/research-quota-capacity.md).

### The scheme
- Config (`config/providers.yaml`, `quota:` section; mirrored as
  `QUOTA_*` module defaults in `brain/memory.py`): owner_weight 1.25,
  member_weight 1.0, active_window_days 7, saturation_threshold 0.50,
  borrow_multiple 2.0, floor_replies 20, planning_haircut 0.20.
- Active set: `last_triggered` table — a user is active if they
  triggered the bot within the rolling 7 days (returning users are
  instantly active; empty set counts as just the triggering user).
- Per-request decision (`check_and_consume_quota`, recomputed every
  turn): share = C x w / sum(w); ceiling = 2x share. Group hard
  ceiling first (used_group >= C -> "group daily limit reached"), then
  the floor (used_user < 20 -> always allow), then the binding limit:
  share when saturated (group used >= 50% of C), else the 2x ceiling
  ("fair share reached"). Already-consumed replies are never clawed
  back. `fair_share_info()` exposes the same numbers without consuming
  (for /stats). The owner is NO LONGER EXEMPT — he gets the 1.25
  weight instead (an exemption would break sum-to-C and let one user
  drain the pool). Capacity unknown (None) fails OPEN with a logged
  warning — a chat bot must not go silent over a missing number.
- Tokens/reply: `token_stats` table, EWMA lambda 0.15 per intent
  (chat/search, anything else bucketed as chat), cold-start blend
  avg = (30x1050 + total) / (30 + n), clamped >= 50. Only successful
  replies are recorded — cache hits and failed calls must never call
  `record_reply_tokens()`.
- Capacity rules: NVIDIA NIM is EXCLUDED from the planning pool
  entirely (trial terms: testing/evaluation only); disabled /
  exhausted entries contribute 0; OpenRouter entries share ONE
  account-wide 50 RPD cap (smallest cap among them, summed usage,
  counted once). Empty entries -> pool 0.0 (fail-closed; no fixed
  fallback number exists in the quota path).
- Degrade mode (`update_degrade_mode` / `get_degrade_mode`, persisted
  in `bot_state`): enter "cheap" when pool/full < 20%, exit only when
  > 30% (dead band), 15-min dwell once a mode is entered.

### NVIDIA NIM model corrected (live verification 2026-11-25)
Seif submitted the NVIDIA NIM key; verified live (models list returns 30
models, key works). BUT the v0.6-configured model
`nvidia/nemotron-3-super-120b-a12b` is RETIRED — it returns HTTP 410 Gone
and is not in the models list. The NIM entry in `config/providers.yaml`
now uses the verified working replacement
`nvidia/nemotron-3.5-super-vl-120b-a12b` (tested: replied in Egyptian
Arabic, 215 total tokens). Also verified NOT to use: `google/gemma-3-12b-it`
(404 on chat despite being listed) and
`nvidia/nemotron-3.5-lightning-30b-a3b` (returns None content —
reasoning-only with default params). Connector doc
`~/workspace/custom-connectors/custom.nvidia-nim/CONNECTOR.md`, helper
`bin/nim.py`. The key lives in the Secure Vault; at deploy time Seif
still pastes it into Render env vars himself (Vault keys are not
available to Render).

### Worked examples (C = 1,500)
| Active | Owner share | Member share | Borrow ceilings (owner / member) |
|---|---|---|---|
| owner + 2 (W=3.25) | 577 | 462 | 1,154 / 924 |
| owner + 14 (W=15.25) | 123 | 98 | 246 / 197 |

### Gemini timezone trap
Gemini RPD resets at midnight Pacific (08:00 UTC), NOT midnight UTC
like Groq/OpenRouter. The router workstream keys Gemini usage rows by
Pacific date; `memory.py` itself stays date-agnostic (it consumes the
entries snapshot it is handed).

### Router + handler integration (landed same day)
- Router: `_date_for(family)` keys Gemini usage rows by Pacific date
  (see trap above), all other families UTC; `pool_snapshot()` /
  `pool_remaining_replies()` expose the live pool; `chat(cheap_only,
  intent)` filters to cheap tiers {groq-20b, cerebras-120b,
  gemini-3.5-flash-lite, gemini-3.1-flash-lite, gemini-gemma} — never
  gemini-3-flash-preview or nvidia-nemotron as primary; successful
  replies record EWMA tokens exactly once (`record_reply_tokens`).
  Provider order, 10s pacing, insult rules, persona untouched.
- Handlers: triggers recorded after the trigger gate (cache-hit turns
  count as activity); quota computed once per turn from live pool +
  active set + `quota:` config; hysteresis degrade replaces the old
  single 20% low-pool threshold (notice only on transition into cheap,
  ≤ once/hour/chat); `/stats` rewritten on live data — pool remaining
  in replies, per-user fair share used/limit, active users, avg
  tokens/reply (chat/search), per-provider remaining, cache hit rate,
  degrade mode + dwell hold. No more hardcoded "150k Groq" / "15 Gemini".
- Known follow-up (not fixed in v0.7): `_classify_429`'s TPD ban still
  computes seconds-until-midnight-UTC, so a Gemini TPD ban lasts until
  UTC midnight, not Pacific midnight.

### Tests
New `tests/test_fairshare_v07.py` (capacity formula, EWMA, active
set, fair-share math, hysteresis, retired surface) + new
`tests/test_router_handlers_v07.py` (Pacific-date keying, pool
snapshot, cheap-only filtering, EWMA-once-per-success, trigger
recording, hysteresis wiring, /stats) + the old fixed-cap tests in
`tests/test_cache_quota_v06.py` / `tests/test_memory_v5.py` /
`tests/test_pacing_v06b.py` replaced with fair-share equivalents.
**255 tests pass in .venv** (was 192), py_compile clean, ruff clean.

## 2026-11-25 — v0.6b: no hourly cap, 10s per-user reply pacing (Seif's call)
- **20/hour burst cap REMOVED** (`brain/memory.py`: `check_and_consume_quota`
  no longer takes `limit_hourly`, no hourly enforcement). Quota is now only
  100/user/day + 1,500/group/day, owner exempt. `hourly_usage` is still
  written (per-hour counts for /stats) but never blocks.
- **Anti-spam is now pacing, not dropping** (`tg/handlers.py`):
  `USER_REPLY_PACE_SECONDS = 10.0` — one reply per user per 10s in a chat.
  A second message is QUEUED: the handler waits until 10s have passed
  since that user's last reply was sent, then runs the turn. The timestamp
  is recorded when the reply is SENT (finally block), not when the message
  arrived, so replies stay >= 10s apart even when the LLM turn takes
  seconds. Replaces the old 3s drop-cooldown ("استنى ثانية" + drop).
  Pacing is per (chat, user); other users are unaffected.
- Tests: 192 pass in .venv (was 187), py_compile clean, ruff clean. New
  tests/test_pacing_v06b.py (pace math, per-user isolation, quota signature
  has no hourly parameter); burst-cap tests rewritten to assert 25 calls
  in one hour are all allowed.

## 2026-11-25 — v0.6 quota expansion (100 replies/user/day, FREE only, within ToS)
Two parallel workstreams (router/providers + prompt/cache/quota), integrated and
verified by the coordinator. **187 tests pass in .venv (pytest tests/ -q, ~15s),
py_compile clean, ruff check passes. `import main` + `build_application()` verified
(6 handlers).** No provider accounts or keys were created; nothing was deployed.

### The hard constraint (from research, non-negotiable)
Multi-account / multi-project rotation to multiply ONE provider's quota is an
explicit ToS violation (Groq AUP bars registering multiple accounts or
orchestrating usage between organisations; Google APIs ToS §2(d) bars
circumventing API limitations; OpenRouter governs capacity globally, so extra
accounts gain literally zero). The bot pools DIFFERENT providers only, one key
per provider, each inside its own published limits. No custom model was built:
no free hosted model has an unlimited quota, and a fine-tune does not raise
limits (limits are GPU-hours, not model quality).

### Fixed — the v0.5 Groq bug (efficiency research)
- `provider_usage` was keyed by provider name ("groq"), so the 150k daily token
  cap was counted COMBINED across gpt-oss-120b + gpt-oss-20b. Groq limits are
  PER MODEL (200k TPD each). Usage is now keyed per (provider, model, date):
  runtime migration in `brain/router.py` (`provider_usage_v2`, old rows preserved
  with `model=''` and counted conservatively toward every entry of that family).
  Caps are now 180k tokens/day per Groq model (safety margin under the real 200k).

### New providers (all OpenAI-compatible, base-URL swap; all OPTIONAL)
- Groq: added `qwen/qwen3.8-27b` as a third Groq tier (strongest Arabic of the
  three Groq models).
- Cerebras: `gpt-oss-120b`, base `https://api.cerebras.ai/v1`, env
  `CEREBRAS_API_KEY`, cap 1M tokens/day. Free-tier status CONFLICTS across
  sources (permanent 1M/day vs card-gated $5/30-day trial since Oct 2026) — on
  401/403/404 the entry is disabled in-memory with a server-side log only, and
  the router continues. Do NOT count its ~950 replies/day until console
  verification.
- NVIDIA NIM: `nvidia/nemotron-3-super-120b-a12b`, base
  `https://integrate.api.nvidia.com/v1`, env `NVIDIA_API_KEY`, cap 10,000
  req/day. FLAG: NIM trial terms say testing/evaluation only, NOT production —
  it is an overflow tier, never the primary (comment in code + providers.yaml).
- OpenRouter :free: env `OPENROUTER_API_KEY`, cap 50 req/day unfunded, models
  `google/gemma-4-31b-it:free` / `nvidia/nemotron-3-super:free`, with required
  `HTTP-Referer` + `X-Title` headers. Emergency spare only (last in every order).
- Gemini (same `GEMINI_API_KEY`, no new key): added `gemini-3.5-flash-lite` and
  `gemini-3.1-flash-lite` (500 RPD each) and `gemma-4-31b-it` (14,400 RPD,
  TPM-managed: in-router rpm guard ~9s between calls, ~7 calls/min sustained).
  `gemini-3-flash-preview` demoted to LAST resort, cap 20 RPD.
- Routing: Tier 1 simple chat Groq-20b → Qwen → Cerebras → NIM → Flash-Lite;
  Tier 2 hard/search Groq-120b → Qwen → Cerebras → Flash-Lite → Gemma →
  Gemini-Flash last; OpenRouter last everywhere. Least-used provider first
  within a tier (most remaining daily budget wins); Retry-After honoured per
  entry; exhausted providers skipped. Missing key = entry skipped silently
  (startup log lists enabled/disabled entries); `NO_KEYS_MSG` only when no
  provider has any key.

### Prompt compression + Groq prefix caching
- `PROMPT_VERSION = "6.0"`. Static prefix is now byte-identical across calls:
  `SYSTEM_BASE` (634 → 448 chars, −29%, all hard rules kept) + hard rules +
  `[STYLE EXAMPLES]` (ALL 7 few-shot pairs — they are static text, so they
  belong in the prefix). Dynamic blocks ([PERSONA CONFIG], [MEMBER], [MOOD],
  [INSULT RULE], [SEARCH RESULTS], deflection line) come AFTER, hard rules
  repeated at the very end. Verified: static prefix 1,444 chars / 722 tokens
  (len//2), identical for two different members/moods/search texts.
- Measured: full system prompt no-search 1,853 chars / 926 tokens (len//2);
  first call ~1,600 tokens, repeat calls pay only the dynamic part (~900 tokens
  incl. history/memory) once the 722-token prefix is a Groq cache hit
  (cached tokens do not count toward Groq rate limits).
- History 8 → 6 messages in the LLM turn; search excerpt stays capped at 800
  chars.

### Exact-match response cache
- New `response_cache` table (normalised_text, intent, mood_bucket, reply,
  created_at; TTL 1h; pruned to last 500 rows). Normalisation reuses
  `core.rules.normalize_arabic`. Mood bucket calm <70 / angry ≥70.
- Greetings/small-talk only — NEVER for search / YouTube / voice / insults /
  grudge replies / replies with citations. Cache is checked BEFORE quota:
  hits cost 0 tokens and 0 quota, are logged (`cache_hit=true`), and counted
  in `get_cache_stats()` (hits/misses/hit_rate, persisted in `bot_state`).

### Kill the wasteful double call + new quota scheme
- Factual questions (intent == search) already searched BEFORE the first LLM
  call; the unknown-retry second call now runs ONLY when no search ran. If
  search ran and the reply is still unknown, the in-character deflection is
  sent directly. Retry rate is logged (`record_unknown_retry` /
  `get_unknown_stats()` in `bot_state`).
- Quota (config-driven defaults in `brain/memory.py`: `USER_DAILY_LIMIT=100`,
  `GROUP_DAILY_LIMIT=1500`, `USER_HOURLY_LIMIT=20`): per-user 100 replies/day
  hard cap + 20/hour burst cap + per-group 1,500 replies/day shared pool (the
  real ceiling). Cached replies do not count; search/YouTube/voice DO count;
  owner (1415214630) is exempt (still counted for /stats). Group exhaustion
  gets its own reply ("يا عم الجروب خلص حصته النهاردة، بكرا نكمل").
- Graceful degrade: when the group pool drops below 20%, cheap tiers only
  (router), cached replies keep working, at most ONE in-character "battery
  low" notice per hour per chat — never a silent dead bot.

### Output caps + /stats
- Chat 600 tokens, search synthesis 600, Groq `max_completion_tokens` 1500
  (was 1500–2000), Gemini 4000 unchanged, Cerebras/NIM/OpenRouter 1500.
- `/stats` (owner-only) now lists ALL providers in `provider_usage` with
  requests/tokens today + remaining-replies estimate at current average,
  per-user top counts, cache hit rate, group-pool remaining %, unknown-retry
  rate.

### Capacity math (at ~1,050 tokens/reply after compression)
| Pool | Budget | Replies/day |
|---|---|---|
| Groq 3 models × 180k tok | 540k tok | ~514 (571 at real 200k) |
| Gemini Flash-Lite ×2 | 500 RPD each | 1,000 |
| Gemini Gemma 4 | 14,400 RPD, 15k TPM, ~7/min | ~9,600 (TPM-bound in practice) |
| Gemini Flash-preview (last) | 20 RPD | 20 |
| OpenRouter :free | 50 RPD shared | 50 |
| **Standing pool (no Cerebras, no NIM)** | | **~11,184/day** |
| + Cerebras (if free tier exists) | 1M tok/day | +~950 |
| + NVIDIA NIM (trial terms only) | 10,000 RPD | +10,000 |
Target is 1,500/day. Even WITHOUT Gemma the standing pool is ~1,584/day —
just above target; with Gemma ~7× headroom. Apply the research's ~50% haircut
for free-tier churn (models deprecated, limits moved without notice):
**~5,500/day expected-pessimistic, ~11,000/day expected** — comfortably above
1,500 either way, PROVIDED Gemma/Flash-Lite numbers hold in Seif's own AI
Studio project. The real binding constraint in practice is TPM/RPM bursts
(Groq 8k TPM window, Gemma 15k TPM), not daily totals — the router spreads
load across providers and the per-user 20/hour burst cap absorbs spikes.
Without Cerebras AND without Gemma the pool is ~1,584/day, i.e. exactly at
target with no headroom — Gemma is the load-bearing addition after Groq.

### Keys needed from Seif (new providers only — code + config ready, no key = entry skipped)
- `CEREBRAS_API_KEY` — console.cerebras.ai (or cerebras.ai dashboard → API Keys).
  Adds ~950 replies/day IF the permanent free tier still exists (verify in the
  console: 1M tokens/day; if it asks for a card / $5 trial, the tier is the
  30-day trial, not permanent — the bot still works, it just disables itself
  after the trial ends).
- `NVIDIA_API_KEY` — build.nvidia.com (NVIDIA Developer Program, phone
  verification; API key under the NIM model page). Adds up to 10,000 req/day
  as an OVERFLOW tier only (trial terms: testing/evaluation, not production).
- `OPENROUTER_API_KEY` — openrouter.ai/keys (free, no card). Adds 50 req/day
  unfunded as an emergency spare. (One-time $10 credit purchase would raise
  this to 1,000 RPD — a paid option, NOT built or required.)
Existing keys (Telegram, Gemini, Groq) unchanged. All three new keys are
optional — the bot starts and runs fine without any of them.

### Deferred (explicitly NOT built in v0.6, with reason + design note)
- Self-hosting (Modal $30 credits / Oracle Always Free VPS + Ollama small
  model): the only truly unlimited path, but it is a hosting project (VPS
  provisioning, hardening, model serving, restarts), not a router change; and
  the pooled free-API capacity above already covers 1,500/day with headroom.
  Design if ever needed: llama-server + Qwen3-8B Q4 (Modal T4, ~6s/reply,
  ~1,000/day within free credits) as Tier 1 bulk chat, Nile-Chat-4B on Oracle
  CPU as always-on fallback; Groq/Gemini keep hard/search. Revisit only if
  live traffic proves the API pool insufficient.
- Semantic cache (local sentence-transformers + FAISS, similarity ≥0.90):
  exact-match cache first (built now); semantic cache adds 20–30% on free-form
  banter per literature but risks stale/wrong-context roasts and needs an
  embeddings model in the image. Revisit after measuring real exact-cache hit
  rate in live traffic.
- Mistral La Plateforme: free-tier status CONFLICTS across sources (one says
  ~1B tokens/month Experiment tier, another says the free API was removed
  Nov 2026 and API needs billing). NOT added as a provider; re-check the
  console before ever adding it — if the Experiment tier exists it would be a
  large simple-chat overflow tier (2 RPM binds, so ~1,000–2,000/day max).
- LLM-as-judge for search, structured BotPlan classifier, Postgres migration,
  plugin rewrite, PTB v22 upgrade — still deferred as in v0.5 (see v0.5 entry).

### Still unverified live (flag in every report, not just here)
- Cerebras free-tier status (conflict above); NIM trial terms (production-use
  clause); Gemma 4 / Flash-Lite live RPD in Seif's own AI Studio project
  (Google publishes no per-model table; limits vary per project, "not
  guaranteed"); real Groq prefix-cache hit rates and actual token savings;
  real yt-dlp download, real Edge TTS/ffmpeg voice, live LLM calls against the
  new caps. No live LLM calls were made in v0.6 — all new-provider
  verification is adapter construction + mocked-error tests only.
- Still blocks the live group test: deploy (Render — Seif pastes his own keys
  in the Render dashboard; Vault keys are NOT available to Render), then live
  test in the group. The test group id is now known (-1005812444791) and the
  bot is already admin there (verified 2026-11-25 22:30 EET).

## 2026-11-25 — v0.7c Northflank deploy prep (health endpoint + BAHGAT_DATA_DIR)
- Health endpoint: new stdlib-only module tg/health.py — ThreadingHTTPServer
  in a daemon thread started from main.py next to run_polling, binds
  0.0.0.0:$PORT (default 8080). GET /healthz (alias /health) returns 200
  {"status":"ok","last_poll_age_seconds":N} when data/heartbeat.json is
  <300s old, else 503; other paths 404. Shuts down cleanly on SIGTERM via
  finally in main(). No new dependency, no secrets in logs (access logs
  silenced). Dockerfile HEALTHCHECK unchanged (still reads the heartbeat
  file); only its comment now mentions /healthz.
- BAHGAT_DATA_DIR env var (core/config.py data_dir()): the data dir was
  hardcoded in 4 places (brain/memory.py, tg/handlers.py, brain/router.py,
  tg/app.py) — now all four resolve from the env var, default
  <project root>/data. Set BAHGAT_DATA_DIR=/data on Northflank so bahgat.db
  lives on the persistent volume; without it the volume is useless.
- DROP_PENDING_UPDATES env var (core/config.py Settings, default true):
  drop_pending_updates was hardcoded True in main.py; set false on the
  deployed instance so messages sent while the bot was down are delivered
  on wake (Telegram holds updates 24h) instead of discarded.
- .env.example documents BAHGAT_DATA_DIR / DROP_PENDING_UPDATES / PORT.
- Deploy guide: docs/DEPLOY-NORTHFLANK.md (Egyptian Arabic) — Combined
  service, Dockerfile build from GitHub main, 1 instance, nf-compute-50
  (0.5 vCPU / 1 GB, $12/mo inside the $20 Sandbox credit), 1 GB volume at
  /data, HTTP port 8080, health check /healthz, all env vars to paste.
- Tests: 8 new in tests/test_health.py (200 fresh / 503 stale / 503 missing /
  /health alias / 404 / $PORT binding / data_dir() override / subprocess
  end-to-end proving all four modules resolve under BAHGAT_DATA_DIR).
  **263 tests pass in .venv, py_compile clean, ruff clean.**
- Verified: import main + build_application() builds 6 handlers;
  DROP_PENDING_UPDATES=false parses to False, default True preserved.
- Pre-existing VM quirk (NOT caused by this change): httpx.Client() raises
  InvalidURL on this VM's NO_PROXY value (bracketed IPv6 literals like
  [::1]); build_application() needs NO_PROXY unset in this VM. Deploy
  target is unaffected.
- Open blockers (not done here): (1) no GitHub repo exists yet for the bot —
  must be created + code pushed to branch main before Northflank can build;
  (2) Northflank requires a payment method for verification even on free
  Sandbox (billing docs, verified); Seif has no international Visa —
  options researched in docs/research-payment-cards-egypt.md (EverTry ~$4
  best, RedotPay, Pyypl, QNB/CIB USD debit; fake/generated cards cannot
  pass Stripe auth). No-card fallback: Render free web service.
