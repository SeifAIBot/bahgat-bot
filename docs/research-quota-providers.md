# Research: free LLM provider landscape, late 2026 (2026-11-25)

Independent subagent research, web sources cited. Token profile: ~1,000-2,000 input + 150-400 output + reasoning tokens per reply, ~2,000 tokens/call planning figure. Target 1,500 replies/day (15 users x 100) needs ~3M tokens/day. No single free provider gives that — answer is pooling + shrinking per-call cost.

## Headline
Yes, 100 replies/user/day reachable for free — but not on current two providers alone, not with current prompt size. Groq + Gemini-Flash together ~300-400 replies/day. Missing capacity from two sources earlier reviews missed: NVIDIA NIM (10,000 requests/day per model, no token cap published) and Gemini's Gemma models (14,400 requests/day, TPM-bound). With those, pooled capacity ~3,000-4,000 replies/day — ~2x target — provided router spreads load and prompt slimmed. Main risk is terms and churn: NIM free tier officially "testing/evaluation only", free lineups retired without warning (Mistral free API died Nov 2026, GitHub Models retired Jul 2026, Cerebras/SambaNova free tiers folded into trials 2026). Re-check every number in provider console before committing.

## Ranked table — standing free tiers (recurring, no expiry)
1. NVIDIA NIM — nemotron-3-super-120b-a12b, nemotron-3-ultra-550b-a55b, openai/gpt-oss-20b, deepseek-ai/deepseek-v4.1-flash, google/gemma-4-31b-it: 40 RPM, 10,000 RPD per model, no published token cap. OpenAI-compat https://integrate.api.nvidia.com/v1. Nemotron 3 multilingual strong; DeepSeek V4.1 good multilingual; Gemma 4 strong Arabic (140+ languages). Catch: trial terms testing/evaluation only NOT production; prompts may be used to train models; free endpoints retired often (gpt-oss-120b, Qwen3.5, GLM-5.1 lost theirs Jul-Sep 2026). Needs NVIDIA Developer Program account + phone verification; not offered in some countries.
2. Google Gemini Gemma 4 (gemma-4-31b-it, via AI Studio): 30 RPM, 15,000 TPM, 14,400 RPD per model per project. OpenAI-compat. Gemma multilingual open model, strong Arabic, good Egyptian in practice (used as WMT26 Egyptian-Arabic judge model family). TPM binding: 15,000 TPM / ~2,000 tok/call ~ 7 calls/min sustained. Fine for 15-person group spread over day, not bursts.
3. Groq — gpt-oss-120b, gpt-oss-20b, qwen/qwen3.8-27b: EACH model 30 RPM, 1,000 RPD, 8,000 TPM, 200,000 TPD per org per model — pooling 3 models = 600k TPD. OpenAI-compat. gpt-oss good Arabic; Qwen3.8 strongest Arabic of three (Qwen best open Arabic performer; best Egyptian-dialect benchmarks among small open models). TPD binds: 200k / 2,000 ~ 100 replies/day per model. 8k TPM binds on search calls (prompt + max_tokens charged upfront).
4. Google Gemini Flash-Lite (gemini-3.5-flash-lite, gemini-3.1-flash-lite): 15 RPM, 250,000 TPM, 500 RPD per model per project. OpenAI-compat. Gemini Flash good Arabic, Egyptian fine with persona prompt. 500/day each. Flash (non-Lite) only 5 RPM / 20 RPD — effectively unusable as workhorse.
5. Cloudflare Workers AI — @cf/meta/llama-3.1-8b-instruct-fp8-fast, @cf/meta/llama-3.3-70b-instruct-fp8-fast, @cf/mistral/mistral-7b-instruct-v0.1: 10,000 neurons/day, no card, resets 00:00 UTC. NOT OpenAI-compat (Workers binding / REST .../ai/run/...). Llama 3.x Arabic serviceable weaker than Qwen/Gemma; 8B drifts to Fusha more — needs dialect guardrail. Neuron math at 2,000 in / 300 out: 70B ~114 neurons/call -> ~87 replies/day; 8B ~22 neurons/call -> ~450/day; 1B ~1,780/day too weak for persona. Real-world ~80 answers/day on 70B at 10k neurons.
6. OpenRouter :free — rotating: nvidia/nemotron-3-ultra:free, google/gemma-4-31b-it:free, nvidia/nemotron-3-super:free, etc. (28 :free ids, 16 chat): 20 RPM, 50 RPD unfunded; 1,000 RPD after one-time $10 credit purchase (account-wide NOT per model). OpenAI-compat. Depends on model; Gemma/Nemotron free variants good. 50/day free spare tire only. $10 once = cheapest "almost free" lever. Lineup rotates fast (Llama/Qwen free delisted Jul 2026). Free providers may log prompts.
7. SambaNova Cloud — Meta-Llama-3.3-70B-Instruct, DeepSeek-V3.1, gpt-oss-120b: DISPUTED/DEGRADED: older docs standing free tier 20 RPM, 20 RPD, 200,000 TPD per model; Nov 2026 sources say ongoing free tier folded into paid Developer tier, free allotment now one-time $5 credit expiring 30 days. OpenAI-compat. Llama 3.3 Arabic OK; DeepSeek V3.1 strong multilingual. Do not build on it until verified live in console. If old tier works: 20 RPD/model nearly nothing anyway.
8. Cohere trial key — Command A (~111B), Command R+: 20 RPM chat, 1,000 API calls/month total, account-wide, never expires. OpenAI-compat-ish. Command decent multilingual, Arabic OK. Trial key forbids production/commercial use. ~33 replies/day — spare only.

## Trial-only / one-time credits (boosters, NOT base)
- Cerebras gpt-oss-120b, qwen-3.8-27b: NO permanent free tier. One-time $5 credit, payment method required, expires 30 days. Inside trial: 5 RPM, 30k uncached / 90k total TPM, 1M tokens/hour and 1M/day per model -> ~500 replies/day for 30 days, then dead. One-month booster only.
- DeepSeek API: reported 5M free tokens/30 days in guides — real-account check 2026-08-31 found granted_balance 0.00 and HTTP 402; grant appears gone. Treat dead. (DeepSeek V4.1 Flash still free via NVIDIA NIM.)
- Together AI / Fireworks / Nebius: ~$1 one-time credits; Together now $15 minimum first purchase, $5 top-ups, no free tier. Dead for $0 design.
- Hugging Face Inference Providers: free account $0 inference credit (PRO $9/mo includes $2). Old serverless free API gone. Dead.
- Alibaba Cloud Model Studio (Qwen): 1M free tokens per model, one-time, 90 days, Singapore only -> ~500 replies once. Booster only.
- Mistral La Plateforme: free API tier GONE — removed early Nov 2026. Browser-only, API needs billing. Dead.
- GitHub Models: retired 30 Jul 2026. Dead.
- xAI: no free tier found. Dead.

## Gemini trap
Google free limits per model per Google Cloud project, vary by project, "not guaranteed". Real projects Oct 2026:
- Gemini 3 Flash / 3.8 Flash / 2.5 Flash: 5 RPM, 250,000 TPM, 20 RPD. Twenty requests/day. Current bot's "Gemini first for hard" burns out by mid-morning. Older guides quoting 1,500 RPD stale (pre-Dec 2025 cuts).
- Gemini 3.5 / 3.1 Flash-Lite: 15 RPM, 250,000 TPM, 500 RPD. Usable Flash.
- Gemma 4 (open model, via AI Studio): 30 RPM, 15,000 TPM, 14,400 RPD. Hidden workhorse.
- Pro models (Gemini 3.1 Pro, 2.5 Pro, Gemini 4 Argon): 0 on free tier.
- RPD resets midnight Pacific; limits per project not per key — second key same project shares same 20 requests.
Multiple projects/accounts: technically each new Google Cloud project gets own free quota, some guides recommend spreading load. Flagged GREY AREA not recommendation: quota multiplication against spirit of limits, Google can flag; do not make it the plan. Same for multiple Groq orgs (per-org limits; multi-accounting to multiply risks bans).

## Pooled capacity estimate (~2,000 tokens/reply)
- Groq 3 models x 200k TPD -> ~300
- Gemini Gemma 4 (TPM-bound, spread over day) -> ~500-1,500
- Gemini Flash-Lite x 2 models x 500 RPD -> ~1,000 (request-capped; only if both used)
- NVIDIA NIM 1 model (10,000 RPD, RPM-bound 40/min) -> 1,500+ easily (RPD not binding; 40 RPM = 2,400/hour)
- Cloudflare Workers AI Llama 3.1 8B -> ~450
- OpenRouter :free (unfunded) -> 50
- Cerebras trial (first 30 days only) -> ~500
- Pooled total standing tiers only (NIM + Groq + Gemma + Flash-Lite + Cloudflare) -> ~3,300-4,800/day
- Pooled total WITHOUT NIM (if NIM rejected on terms) -> ~1,800-3,300/day — still above 1,500 target, no headroom
Caveats: ceilings not guarantees — TPM/RPM bind during bursts (15-person group chatting at once hits Groq 8k TPM and Gemma 15k TPM within a minute). Router must queue and spread across providers; per-user daily caps still matter as abuse protection, not capacity limit.

## Shrink cost per reply
- Prompt slimming (biggest lever): system ~570 tokens + 8 history + 1,500-char search excerpt ~ 2,000 tok/call. Cutting history 8->4, search excerpt 1,500->800 chars, output cap 400 tokens brings plain chat to ~1,200-1,400 tokens — ~40% more replies from same quotas.
- Reasoning tokens silent cost: gpt-oss/Gemini reasoning counts against TPM/TPD. reasoning_effort="low" + include_reasoning=False + max_completion_tokens 1,500-2,000 on Groq (not 4,000) prevents one call eating 6,000+ tokens of per-minute window.
- Exact-match cache: greetings ("بهجت ازيك؟") and repeated questions 10-20% of group traffic; caching costs zero tokens.
- Route by cost: simple chat -> cheapest/smallest (gpt-oss-20b, Gemma 4, NIM nemotron-3-super); hard/search -> 120B-class only.

## "Custom model" — what that can actually mean for free
No free way to train/host frontier-class custom model. Free options:
1. Fine-tune small open model on Bahgat transcripts (Qwen3-4B or Gemma-3-4B) on free Colab GPU, self-host on Oracle Always Free VPS. Oracle Always Free ARM VM now 2 OCPU / 12 GB RAM (halved June 2026; older guides say 4/24 GB). 3B model ~15-25 tok/s on 4 CPUs (slower on 2); 8B ~5-10 tok/s -> 100-token reply 10-20s. Unlimited requests, $0, forever — only truly unlimited path — but slower/weaker than gpt-oss-120b, Arabic quality of 3-4B needs persona prompt + examples to stay Egyptian. Best use: overflow/last-resort fallback, not primary.
2. Provider fine-tuning (OpenAI, Together, etc.) — all paid. Not option under $0.
3. LoRA fine-tune via free Colab + serve through free inference provider — no free provider hosts your fine-tune. Dead end.
Recommendation: do not build custom model yet. Add providers first (weeks of capacity), keep transcript work (Whisper + examples) as style layer in prompt — already gives most of "custom" feel for free.

## Recommended provider pool (in order)
1. NVIDIA NIM nvidia/nemotron-3-super-120b-a12b — primary workhorse everyday chat (10k RPD/model, fast). Fallback within NIM: openai/gpt-oss-20b, then deepseek-ai/deepseek-v4.1-flash.
2. Groq openai/gpt-oss-20b (simple) -> openai/gpt-oss-120b (hard) -> qwen/qwen3.8-27b (Arabic-heavy / third pool) — 100 replies/day each, fastest.
3. Gemini gemma-4-31b-it — bulk fallback (14,400 RPD, TPM-managed, ~7 calls/min sustained).
4. Gemini gemini-3.5-flash-lite / gemini-3.1-flash-lite — 500 RPD each, search synthesis.
5. Cloudflare Workers AI Llama 3.1 8B — last resort before "quota finished" (~450/day).
6. OpenRouter :free — emergency spare only (50/day unfunded). Optional $10 one-time unlocks 1,000 RPD permanently — single cheapest capacity purchase if $0 rule ever relaxed by exactly $10.
7. Gemini gemini-3-flash-preview — demote to last resort: 20 RPD rounding error; keep only for hardest 20 questions/day.
Per-user caps then raised to 100/user/day (group daily cap ~1,500-2,000 as safety valve, per-minute spreading so TPM limits don't trip), because pooled ceiling supports it. Keep caps — abuse protection not capacity — set from pooled math not one provider's limit.

## Verify live before relying
- NIM: confirm nemotron-3-super-120b-a12b still has Free Endpoint on build.nvidia.com today, read current API Trial Terms (production-use clause).
- Gemini: read Seif's own project limits at aistudio.google.com — Gemma 4 and Flash-Lite numbers vary by project.
- SambaNova: check console — old free tier vs $5-credit-only unresolved.
- Groq: confirm qwen/qwen3.8-27b still on Free plan (replaced qwen3.6-27b during 2026).

Sources: blog.laozhang.ai groq-api-free-tier; github mnfst/awesome-free-llm-apis; flatkey.ai free-llm-apis-2026; imisofts.com gemini-api-free-tier-limits; docs.orchable.app gemini-api-guide; mangomindbd.com free-ai-platforms-daily-limits-2026; openrouter.ai collections/free-models; dev.to tariqnasser free-llm-api-tiers-october-2026; github mvalentsev awesome-free-ai-coding nvidia-nim.md; horizonlux.com nvidia-nim-free; dev.to tariqnasser; stacksfree.com cerebras-free-tier-guide-2026; grabaicredits.com cerebras; verna.one free-llm-apis; volksdroid.app sambanova-cloud; developers.cloudflare.com workers-ai pricing; dev.to yimtheppariyapol cloudflare-workers-ai; dev.to akaranjkar08 cloudflare-free-tier-2026; enrai.web.id mistral-free-api; aionx.co together-ai-review; efreedirectory.com together-ai-no-free-tier; aionx.co huggingface-inference-api; klymentiev.com huggingface-inference-api; toolfreebie.com deepseek-free-api; inferencehub.org best/free-llm-apis; macrostack.net ai-api-prices/free; dev.to akdevcraft 0-personal-agentic-ai-assistant-running-local-llm; peculiarengineer.com self-host-ollama-oracle-free-vast-gpu; arxiv.org 2505.18383v3; statmt.org wmt26 2026.wmt-1.68.pdf.
