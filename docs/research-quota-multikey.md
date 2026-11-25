# Research: multi-key / multi-project rotation to scale free LLM tiers (2026-11-25)

Independent subagent research, web sources cited. Target: 100 replies/user/day x 15 users = ~1,500 replies/day, ~2.25M tokens/day at ~1,500 tokens/call.

## Bottom line
Target NOT achievable on free tiers within providers' terms. Rotating multiple free accounts/projects of the SAME provider to multiply quota is an explicit ToS violation at Groq and Google, and pointless at OpenRouter (globally governed). Legitimate pooling of DIFFERENT providers + token-shrinking honestly reaches ~400-600 replies/day, stretchable to ~700-900/day. Only routes to full 1,500: self-hosting (unlimited but weak/slow on free hardware) or small paid spend.

## ToS — quoted
- Groq Terms of Use: "Attempting to or circumventing the free tier limits of the Services, including any action that imposes, or may impose an unreasonable or disproportionately large load on our infrastructure, or sending Groq traffic beyond rate limits." Groq AUP (2025-10-15): not to "use the Cloud Services and AI Model Services beyond published parameters, rate limits, or use limitations, including by registering multiple accounts or orchestrating usage between multiple organizations". Limits per ORGANISATION not per key — second key in same org gives no more room. Services Agreement bars use "in a manner intended to avoid incurring fees", "no obligation to provide multiple accounts". Verdict: multiple Groq accounts/orgs to multiply free quota = banned in writing. Risk: account termination, loss of key bot already runs on.
- Google APIs ToS Section 2(d) "API Limitations": "Google sets and enforces limits on your use of the APIs... You agree to, and will not attempt to circumvent, such limitations documented with each API. If you would like to use any API beyond these limits, you must obtain Google's express consent..." Gemini limits per Cloud PROJECT not per key; rotating across several free-tier projects owned by one person to combine allowances "should not be assumed compliant"; correct handling of 429 is respect quota and queue/pause, not silently switch projects (discuss.ai.google.dev thread). Google enforced rotation bans Feb 2026 wave in Antigravity/Gemini CLI (Threads anecdotal, weak evidence). Verdict: multiple AI Studio/Cloud projects to multiply free quota = ToS violation 2(d).
- OpenRouter: "Making additional accounts or API keys will not affect your rate limits, as we govern capacity globally." Free :free models 20 RPM, 50 RPD shared across all free models; 1,000/day after one-time $10 lifetime credit purchase. Verdict: multi-account rotation gains literally zero.
- "One project per group member" idea: NOT legitimate — same circumvention with extra steps; puts other people's accounts at risk if they lend credentials. Do not build.

## What IS legitimate
- Cross-provider pooling (Groq + Gemini + SambaNova + Cloudflare + OpenRouter :free, each inside own published limits) — separate grants, normal multi-provider failover.
- Multiple keys in ONE Groq org / ONE Gemini project — no capacity gain (per-org/per-project), legitimate as failover/redundancy if key revoked/leaks; rotate on 401, never to dodge 429.
- Quota increase requests — ToS-sanctioned path (Google Cloud Console Quotas, requires billing for Gemini; Groq Developer/sales). Paid tier.
- A second genuinely separate human's account (friend runs own bot for own group) — separate person/use, but NOT pooling their key into Seif's bot (re-becomes orchestration across organisations).
- Self-hosting open models (Ollama on Oracle Always Free VPS) — own hardware, own weights, no provider ToS applies. Unlimited requests.
- One-time $10 OpenRouter top-up — documented provider-endorsed: 50 -> 1,000 free-model RPD, credits unspent. +950 replies/day.

## Realistic legitimate capacity (replies/day at ~1,500 tok/call)
- Groq gpt-oss-120b: 30 RPM, 1,000 RPD, 8,000 TPM, 200,000 TPD -> ~130 (TPD binds)
- Groq gpt-oss-20b: same per-model caps -> ~130
- Gemini gemini-3-flash-preview: per project, reported 20 RPD (planning) to 250-1,500 RPD -> 20-250
- SambaNova gpt-oss-120b / llama-3.3-70b: 20 RPM, 20 RPD, 200,000 TPD per model -> 20/model, ~40-80 across 2-4 models
- OpenRouter :free (no credits): 20 RPM, 50 RPD shared -> 50
- Cloudflare Workers AI: 10,000 Neurons/day (Llama 3.3 70B ~124 neurons/call) -> ~75-130
- Cerebras: NO permanent free tier — one-time $5 credit, expires 30 days, card required, 5 RPM / 1M TPD per model -> ~650/day but only <=30 days, then paid
- Mistral La Plateforme: free API access removed early Nov 2026 — browser-only, API needs billing -> 0
- GitHub Models: retired 30 July 2026 -> 0
Legitimate standing pool (excl expiring Cerebras): ~400-600 replies/day = ~27-40/user/day for 15 users, not 100. With token-shrinking ~700-900/day. Cannot reach 1,500/day free within ToS.

## Two real ways to reach 1,500/day
(a) Self-hosted: Ollama on Oracle Always Free VPS, zero API costs, no rate limits, OpenAI-compatible. Reality: Oracle free VPS no GPU ~4GB RAM, realistic models Qwen 2.5 0.5B-4B / Qwen3 4B — far weaker than gpt-oss-120b at persona/Arabic/reasoning, slow (tens of seconds/reply on CPU). Works as OVERFLOW tier (when hosted tiers exhausted, answer with local small model, or greetings/simple chat only), not like-for-like replacement. No ToS risk.
(b) Tiny paid spend: Groq Developer pay-as-you-go gpt-oss-20b $0.075/1M in, $0.30/1M out. 1,500 replies/day ~2.25M tokens ~ $0.30-0.50/day ~ $10-15/month. OpenRouter $10 once unlocks 1,000 free-model RPD forever — combined with pool nearly closes gap alone. Cerebras Developer after trial 1M TPM no daily cap, pay-as-you-go.

## Safe rotation design (legitimate version only)
Pool PROVIDERS not accounts. providers.yaml one entry per PROVIDER one key each, never two keys same provider account: groq-120b, groq-20b, gemini-flash, sambanova-120b, sambanova-llama70b, cloudflare-llama70b, openrouter-free, ollama-local (overflow).
Routing: 1. classify simple chat -> cheapest/fastest available (groq-20b first); hard/search -> groq-120b, then gemini, then sambanova-120b. 2. pick provider with most remaining daily budget (least-used), skip any with active 429/cooldown. 3. on 429 honour Retry-After, mark THAT provider exhausted until reset (TPM ~60s; TPD midnight UTC or midnight Pacific Gemini), rotate to next. Never retry same provider to dodge cap. 4. when all hosted exhausted: local Ollama overflow if deployed, else in-character "quota finished for today" reply.
Per-provider usage table (extend provider_usage): provider, model, date, requests, tokens_in, tokens_out, last_429_at, exhausted_until, daily_cap_requests, daily_cap_tokens + provider_state(provider, rpm_window_count, window_start) for RPM guards. Read provider rate-limit headers every response (Groq x-ratelimit-remaining-*, OpenRouter GET /api/v1/key), stop BEFORE 429.
Monitoring: JSON log per call + owner /stats remaining replies per provider, estimated hours left; alert owner DM when total remaining pool <20% of day's budget.
Token-shrinking: exact-match response cache for greetings (~10-20% group traffic repeats), shorter system prompt + 6 instead of 8 history (~15-20% fewer input tokens), output cap 400-600 (v0.5 done), route simple chat to smallest adequate model. Combined plausibly lift legitimate pool ~500 -> ~700-900/day — still short of 1,500, honest free maximum.

## Recommendation
1. Do NOT create extra Groq accounts or Gemini projects — written into both ToS, risks losing keys bot depends on, OpenRouter makes it pointless.
2. Build legitimate cross-provider pool (Groq 120b+20b, Gemini, SambaNova x2, Cloudflare, OpenRouter :free) — ~400-600/day, raise per-user cap 30 -> ~35-40/day honestly, not 100.
3. Add Ollama overflow tier on Oracle free VPS as safety net when pool dry (simple chat only, visible quality trade-off).
4. If 100/user/day truly required, cheapest honest options: one-time $10 OpenRouter top-up (->1,000 free RPD, nearly closes gap alone) or ~$10-15/month Groq pay-as-you-go. Provider-endorsed paths, not workarounds.
5. Revisit per-user cap after a week of real traffic: 15 users x 100 is worst-case ceiling; measured usage usually far lower, pool may cover real demand even if not theoretical maximum.

Sources: Groq ToS PDF cdn.sanity.io; Groq AUP via wiki.licenseware.io; mizanstack.com groq-free-tier; developers.google.com/terms; discuss.ai.google.dev multiple-projects-fallback-keys; tokeneggs.com free-ai-api-keys; liverpoolseo.org freegeminiapitier; threads.com devoresyah Antigravity bans (anecdotal); blog.laozhang.ai openrouter-alternatives-free-models; modelhubby.com guides/openrouter; teamday.ai openrouter-free-model-limits-2026; troiana.net guides/sambanova; costbench.com best-llm-api-with-free-tier; developers.cloudflare.com workers-ai pricing; dev.to akaranjkar08 cloudflare-free-tier-2026; stacksfree.com cerebras-free-tier-guide-2026; grabaicredits.com cerebras; enrai.web.id mistral-free-api; vuncloud.com github-models-api-guide; dev.to samhartley_dev ollama-0month; devplace.net ollama telegram bot VPS; github.com DeepakSilaych/free-api-gateway; 266d.com credential-pools; pypi.org robin-router.
