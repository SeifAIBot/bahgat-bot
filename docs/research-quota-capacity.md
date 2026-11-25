# Research: estimating & tracking daily capacity for a multi-provider free-LLM chatbot (2026-11-25)

Independent web research (10 searches; LiteLLM, Portkey, Groq/OpenRouter/Gemini docs, rate-limit calculators, Langfuse cost tracking, token-bucket/fair-share, EWMA + hysteresis). Read-only.

## 1. How production routers estimate remaining daily capacity in real time
Same pattern everywhere (LiteLLM Router, Portkey, Cloudflare AI Gateway): every provider entry carries declared caps, every call updates a local usage counter, "remaining" is always `cap − used`, converted into the unit the product thinks in (here: replies).
- **One counter per (provider, model, day), not per provider.** LiteLLM tracks RPM/TPM/RPD/TPD per deployment; TPM/TPD best-effort (token count unknown until response arrives), RPM/RPD hard counters. Groq limits per model per org, Gemini per project per model, OpenRouter free-model counter account-wide across all `:free` models — counter granularity must match the provider's own granularity.
- **Convert every cap into replies, take the binding (smallest) one:** per provider entry: `replies_remaining = min(RPD_remaining, TPD_remaining / avg_tokens_per_reply, TPM_sustainable_per_day / avg_tokens_per_reply)`; `pool_remaining = Σ replies_remaining` over healthy entries.
- **Read the provider's own live numbers wherever they exist.** Groq returns `x-ratelimit-limit/remaining-requests`, `x-ratelimit-limit/remaining-tokens`, `x-ratelimit-reset-*` on every response, `retry-after` on 429s. OpenRouter exposes a live exact counter via `GET /api/v1/key` → `free_model_daily_requests: {used, limit, remaining}` + reset timestamp; 429s carry `X-RateLimit-Limit/Remaining/Reset`. Gemini publishes NO live remaining counter and no fixed per-model table — limits per project, shown only in AI Studio; daily quotas reset at **midnight Pacific time**, not UTC. So for Gemini the bot's own SQLite counter is the only source of truth; for Groq/OpenRouter headers are a second source that can correct local drift.
- **Planning haircut, not the raw cap.** Calculators use a 20% safety buffer by default; "planning utilization target" 70–85%. LiteLLM's TPM/TPD are best-effort for exactly this reason — a pool computed at 100% will 429. For churning free tiers, 20% is the floor; 30–50% is the pessimistic planning number.
- **A provider that dies mid-day is removed from the pool, not retried into.** LiteLLM rules: 429 → cooldown immediately; >50% failures in the current minute → cooldown; 401/404/408 → cooldown (default 5s, configurable). Cooldown applies per deployment, not per model group. Portkey: ordered fallback targets; on 429/500–504 move to target 2 in milliseconds. For this bot: 401/404 = disable entry for rest of day (retrying cannot help); TPM-429 = cool down for Retry-After (or exp. backoff 0.5–8s + jitter), retry another provider; TPD-429 = mark exhausted until midnight. Never let one provider's failure block the others.
- **Owner weighting is a multiplier on the fair share, not a separate pool.** One shared budget, single shared limiter above all users, per-user sub-budgets derived from it. `fair_share = pool_remaining / Σ weights`, owner weight 1.25, others 1.0.

## 2. Measuring average tokens-per-reply reliably
- **Measure from `usage`, never from character counts.** Read `usage.prompt_tokens` and `usage.completion_tokens` from real responses. Character heuristics (len/2, len/3) are fine for pre-call prediction (reserve a conservative estimate upfront; return unused tokens after completion), not for measurement.
- **Separate averages by call type.** Three buckets: `chat` (~1,050 tok), `search` (~2,000–2,400 tok), `voice/YouTube` (LLM cost small, but reply still consumes one pool slot). Honest version: `avg = Σ(type_avg × type_share)` recomputed from the last N calls, or track blended EWMA *and* per-type means and use the per-type mean when intent is known before the call (it is — intent is detected first).
- **EWMA over last ~100–200 calls, plus median and p95.** `EWMA_t = λ·x_t + (1−λ)·EWMA_{t−1}`, λ ≈ 0.1–0.2. Keep rolling window of last 200 completed calls per (intent, provider-model) in SQLite, or just EWMA + count + sum-of-squares in one row. Median for "typical reply", p95 for reserve planning. **Trim outliers**: winsorize at p99 or drop top 1–5% (a 4,000-token reasoning spiral or pasted 4,096-char message is not representative).
- **Reasoning tokens count.** Count `prompt_tokens + completion_tokens` (incl. reasoning) as the call's cost; cached prompt tokens count as 0 where the provider says so (Groq: cached tokens don't count; Gemini context caching is paid-only, no discount).
- **Cache hits and failed calls**: cache hits cost 0 tokens — exclude from the average. Retries: count each attempt's tokens in usage, count the *reply* once; add a retry factor (×1.05–1.10) if retry rate is measurable.
- **Cold start**: before ~30 measured calls, fall back to configured 1,050 estimate; blend `avg = (30×1050 + Σ measured) / (30 + n)`.

## 3. How often to recompute, and where to store it
- **Recompute lazily on every quota check (per call), from counters — not on a timer.** LiteLLM: counters updated on every call, routing reads them live; "DB writes are NEVER on the hot path… post-processing is async background tasks". For a single-instance bot: **authoritative state in SQLite** (already the case: `provider_usage`, `daily_usage`, `response_cache`) — survives restarts; a restart must not resurrect a dead provider or forget today's burn. **In-memory mirror** (dict of per-entry used/disabled) updated on each call, so the quota check is a dict lookup. Derived numbers (pool remaining, per-user fair share) computed on read, never stored — never stale by more than one call.
- **Timer is only for re-syncing header-derived remaining** — but those only arrive *with* calls, so a timer adds nothing unless the bot makes a probe call, which would burn quota. Don't probe. Reconcile on every real response: if the header says fewer remaining than the local counter implies, trust the header and adjust local `used` upward.
- **Daily reset**: one row per (provider, model, date); reset is implicit (new date = new row). Timezone trap: Groq/OpenRouter reset 00:00 UTC; **Gemini RPD resets at midnight Pacific (08:00 UTC)** — key Gemini usage by Pacific date (one `time.strftime` with a TZ offset), or accept up to 8h of over/under-counting.

## 4. When the estimate is wrong
- **Overestimated (provider 429s mid-day)** — the normal case. Layered response: (1) fail over, don't wait — if another healthy deployment exists, try immediately with zero wait; only when *no* healthy deployment remains, honour Retry-After (up to 1 min) or exp. backoff 0.5–8s + jitter. (2) Cooldown the failed entry per-deployment (5s default; Retry-After if given; TPD-exhaustion until midnight UTC; 401/404 rest of day). Gradual reintroduction, no probe request. (3) Degrade in tiers, not a cliff: pool >20% = normal routing; 5–20% = cheap tiers only, shorter outputs, cache first; <5% = cache + one in-character "battery low" notice per hour, then silence. Cached replies keep working at every tier (0 tokens). (4) Never retry a request that already consumed budget blindly — fail over to a different provider.
- **Underestimated (pool sits unused)**: (a) header reconciliation — Groq/OpenRouter headers tell the real remaining; trust them; (b) end-of-day release — pool is use-it-or-lose-it at midnight, so relax the haircut as the day ends (after 20:00 UTC, drop the 20% safety margin to 5%), and let per-user fair shares grow as `pool_remaining / active_users` recomputed live.
- **Avoiding flapping**: hysteresis + dwell + smoothing. Enter cheap-tier mode at pool <20%, exit only at pool >30% (dead band). Dwell time: once a mode is entered, stay at least 15 minutes regardless of the recomputed number (mode sticky; quota numbers still update every call). Smooth the signal: base mode decisions on the EWMA of pool remaining (or require 3 consecutive checks below threshold). Cooldowns are per-entry, mode is global — keep them separate.

## 5. Worked example for this bot
Assumptions: avg cost 1,050 tokens/reply; planning haircut 20% (×0.8); 10 users; owner weight 1.25, others 1.0 (Σ weights = 10.25). NIM shown separately — trial terms evaluation-only, NOT in the planning pool. TPM burst check: Groq 8,000 TPM ÷ 1,050 ≈ 7.6 replies/min per model (×3 ≈ 23/min); Gemma 15,000 TPM ≈ 14/min; Flash-Lite 250k TPM ≈ 238/min — none binds the daily total, only bursts.
### 06:00 UTC — fresh day, all providers healthy
| Entry | Cap | Replies/day |
|---|---|---|
| Groq gpt-oss-120b | 200,000 TPD; 1,000 RPD | min(1000, 200000/1050=190) = 190 |
| Groq gpt-oss-20b | same | 190 |
| Groq qwen3.8-27b | same | 190 |
| Cerebras gpt-oss-120b | 1,000,000 TPD | 952 |
| Gemini Flash-Lite ×2 | 500 RPD each | 1,000 |
| Gemini Gemma 4 | 14,400 RPD; 15,000 TPM | 14,400 (TPM: ~14.3/min × 60 × 16h ≈ 13,700 — near-tied; count 14,400 but least-trusted) |
| Gemini Flash-preview | 20 RPD | 20 |
| OpenRouter :free | 50 RPD | 50 |
| **Raw pool (excl. NIM)** | | **16,992** |
| NVIDIA NIM (excluded) | 10,000 RPD | +10,000 if counted |
- After 20% haircut: 16,992 × 0.8 = **13,594 planning replies**. Equal split: 13,594 / 10 = **1,359/user/day**. Owner-weighted unit = 13,594 / 10.25 = **1,326**; owner = **1,658**; each other user = **1,326**.
### Midday recompute — 40% of Groq used, Cerebras returns 401 (disabled)
- Groq used 80,000/200,000 per model → 120,000 left → 114 replies/model. Cerebras 401 → disabled, 0.
- New raw pool: 114×3 + 0 + 1,000 + 14,400 + 20 + 50 = **15,812**. After haircut: **12,650** remaining.
- Per-user remaining (of the *remaining* pool): equal 1,265; owner-weighted unit 1,234, owner 1,543, others 1,234. Then subtract what each user already used: `user_remaining = fair_share − user_used_today` (floor 0). A user who used 200 has ~1,034 left; a user who used 0 has the full 1,234 — pool reallocates toward whoever is actually talking.
- **Sensitivity**: losing Groq-40% + all of Cerebras only drops the pool 16,992 → 15,812 (−7%) because **Gemma is ~85% of the pool**. Real risk is Gemma: if Seif's AI Studio project grants Gemma 500 RPD instead of 14,400, the morning pool collapses to ~2,500 raw (~2,000 after haircut, ~195/user) — a 6× error from one unverified number. Mitigations: verify Gemma/Flash-Lite live RPD in AI Studio before promising anything; keep haircut ≥20%; let header/local-counter reconciliation correct the estimate downward the moment Gemma 429s.

## 6. Sources
- LiteLLM load balancing: https://litellm.vercel.app/docs/proxy/load_balancing
- LiteLLM routing: https://github.com/berriai/litellm-docs/blob/HEAD/docs/routing.md
- LiteLLM reliability (cooldowns, Retry-After ≤1 min, backoff 0.5–8s + jitter): https://docs.litellm.ai/docs/router/learn/reliability
- LiteLLM architecture patterns: https://github.com/srobinson/nancyr/blob/HEAD/research/05-litellm-patterns.md
- Portkey failover: https://portkey.ai/docs/guides/use-cases/enterprise-ready-unified-api
- Portkey + Cerebras: https://inference-docs.cerebras.ai/integrations/portkey
- Rate-limit calculator (binding limit = min of ceilings, 20% buffer): https://aq-score.com/tools/ai-api-rate-limit-calculator
- LLM API rate limits explainer: https://dailytech.ai/llm-api-rate-limits/
- Free-tier limits tracker: https://app.plugsky.com/tools/free-api-limits-tracker
- Rate-limit calculator & concurrency (70–85% utilization): https://www.ctxwire.com/articles/ai-api-rate-limit-calculator/
- OpenRouter free-tier limits, live `GET /api/v1/key`: https://github.com/trained-assist/trained-assist-llm-ladder/blob/HEAD/docs/free-tier-limits.md
- OpenRouter free models 2026: https://dev.to/lightningdev123/openrouters-free-model-apis-in-2026-working-with-request-limits-instead-of-token-caps-413f
- OpenRouter rate limits & 429 headers: https://fast.io/resources/openrouter-rate-limit/
- Groq rate limits & `x-ratelimit-*` headers: https://fast.io/resources/groq-rate-limit/
- Groq free API guide: https://apidog.com/blog/groq-api-free/
- Groq 413 vs 429, header parsing: https://github.com/danja/valis/blob/HEAD/docs/rate-limit-advice.md
- Retry strategies & LiteLLM cooldowns: https://blog.redlinesoft.net/posts/retry-strategies-model-rate-limits/
- AI gateway 429 comparison: http://zenmux.ai/blog/ai-gateway-rate-limit
- Langfuse tracing & budgeting: https://blog.zolty.systems/posts/2026-06-13-langfuse-tracing-budgeting-agents/
- LLM cost monitoring: https://www.475cumulus.com/articles/monitoring-llm-costs
- Cost per task, median + p95: https://www.dreaming.press/posts/agent-cost-per-task-not-per-call-langfuse-otel-attribution.html
- AI agent rate limiting (token bucket, circuit breaker, shared-quota problem): https://github.com/openlegion-ai/landing/blob/HEAD/src/content/learn/ai-agent-rate-limiting.md
- Rate limiting & backpressure (token-aware limiting, soft reservation): https://zylos.ai/research/2026-02-25-rate-limiting-backpressure-ai-agent-apis/
- Health checks & failover (EWMA, hysteresis, flapping): https://senior-stack.uz/Roadmap/Architecture/system-design/08-load-balancers/05-health-checks-and-failover/professional/
- EWMA / SPC: https://apxml.com/courses/deploying-diffusion-models-scale/chapter-5-monitoring-maintaining-deployed-models/detecting-performance-regressions
- Gemini 429 (per-project limits, midnight Pacific reset): https://aionx.co/technical-ai-tutorials/gemini-api-429-resource-exhausted/
- Gemini production architecture: https://markaicode.com/architecture/gemini-api-inference-architecture/
- Gemini & Claude rate limits 2026: https://oxyy.ai/blog/fix-gemini-and-claude-api-429-rate-limits

## Bottom line for the implementation
1. **Formula**: `pool_remaining = Σ min(RPD_left, TPD_left / avg_tok) × 0.8` over healthy entries; `fair_share = pool_remaining / Σ weights` (owner 1.25); `user_remaining = fair_share − user_used_today`.
2. **Measure** avg tokens/reply from `usage.*` per call, EWMA λ≈0.15, separate chat/search means, median + p95, winsorize top 1%, reasoning tokens included, cache hits excluded.
3. **Recompute on every quota check** from SQLite counters + in-memory mirror; reconcile against Groq/OpenRouter response headers on every call; no timer, no probing.
4. **Degrade with hysteresis** (enter cheap-tier mode <20%, exit >30%, 15-min dwell), per-entry cooldowns (429→Retry-After/5s, TPD→midnight, 401/404→rest of day), cached replies always free.
5. **Biggest risk is Gemma**: ~85% of the pool, live RPD unverified in Seif's project. Verify in AI Studio first; the dynamic quota self-corrects downward on the first Gemma 429, but the morning promise should be sized on verified numbers.
