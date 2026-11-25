# X posts review — read with x-scout, no account (2026-11-26)

Method: free no-login CLI x-scout (github.com/JunJayDev/x-scout), cloned to /tmp/x-scout, run as `node bin/x-scout.js read <url>`. Reading needs no key (search would need a Grok key — not used). All 8 posts fetched successfully. Profile timeline for @0xCodila was flaky (one run returned 10 recent posts, a second run errored) — the posts that did return are all on one topic.

Score: **1 of 9 clearly USEFUL** (VoiceStudio), 1 lead not yet actionable (uncensored models), 7 NOT useful.

## 1. @Aiwithkumail — VoiceStudio — USEFUL
- Post: https://x.com/Aiwithkumail/status/2125505904845955544 (2026-11-25 08:24Z, 32k views, 386 likes, 501 bookmarks)
- Claim: a solo dev open-sourced a 100% free ElevenLabs replacement that runs entirely locally — clone a voice from one clean reference clip, dub video into 646 languages, audiobooks/dictation/transcription, 14 TTS engines, no per-character billing, no caps, no audio leaves the computer. Repo in the follow-up reply: https://github.com/debpalash/VoiceStudio
- Verified against the repo (read 2026-11-25): real and big — 118,357 stars, 8,419 commits, created 2026-04-09, AGPL-3.0, Electron app + FastAPI backend, Docker images (CPU + CUDA) on GHCR, local API + MCP, no account needed for the free app. Default engine is OmniVoice (k2-fsa) with zero-shot cloning; the engine catalog lists 17 speech generators including CosyVoice 3, IndexTTS 2.5, VoxCPM2, MOSS-TTS, **GPT-SoVITS** (external server), KittenTTS, Sherpa-ONNX. XTTS is NOT included (independent code grep confirms; only "IndexTTS" matches). The post's numbers are stale (19.4K stars at post time vs 118K now; "14 engines" vs 17 in the catalog) but the core claim checks out. One reply ("API key stealer… scammer") is an unsubstantiated accusation — nothing in the repo supports it. One reply warns it will not run smoothly on an average consumer computer — fair: it wants a GPU for practical speed; CPU works but slow.
- How we would use it (voice-clone training, in progress): (a) test OmniVoice zero-shot cloning with a clean Bahgat clip as an alternative/complement to the planned XTTS v2 zero-shot test; (b) it already bundles GPT-SoVITS as an engine, which could replace the hand-rolled RVC/GPT-SoVITS training setup; (c) its local API could serve voice generation offline. Caveats: voice inference must stay OFF Render free (512 MB, no GPU) — generation is a batch/offline step, not a runtime component; Arabic/Egyptian-dialect quality is unverified and must be tested with a real sample; default OmniVoice weights are CC-BY-NC (non-commercial). The bot's runtime voice path (Edge TTS → RVC) is unchanged by this.
- Next step: hand the VoiceStudio lead to the voice-training work — run OmniVoice zero-shot on a clean Bahgat clip on free Colab GPU and compare with XTTS v2.

## 2. @Lucy_love_AI — 10 scraping repos — NOT useful (one small note)
- Post: https://x.com/Lucy_love_AI/status/2125396894784561159 (2026-11-25 01:11Z, 126k views, 2.1k likes, 3.3k bookmarks). Chinese-language list of 10 GitHub scraping repos: firecrawl, crawl4ai, browser-use, crawlee, scrapy, markitdown, Scrapling, scrcpy, autoscraper, curl-impersonate.
- Our bot already does DuckDuckGo search + urllib page fetch with SSRF validation and parallel top-3 grounding. crawl4ai/browser-use need Playwright/a browser — too heavy for Render free (512 MB). firecrawl is a paid API. Small note only: Microsoft's markitdown (pages/PDF/Office → clean markdown) could be a lightweight future upgrade for page extraction before LLM grounding — not worth doing now.

## 3. @0xShoopy — CLAUDE.md token diet — NOT useful
- Post: https://x.com/0xShoopy/status/2125566562547499148 (2026-11-25 12:25Z, 41k views, 408 likes, 844 bookmarks). About Matt Pocock's 6-word CLAUDE.md and a prompt to prune Claude Code context files (count/cut/move rules into on-demand skills); quotes an article on getting 3x more from Claude limits.
- This is Claude Code agent hygiene, not bot runtime. Our prompt was already compressed in v0.6 (SYSTEM_BASE 634→448 chars) and the router is token-aware. Nothing to apply.

## 4. @pengsonal — TOP 10 UNCENSORED AI MODELS — lead, NOT actionable now
- Post: https://x.com/pengsonal/status/2125542566024396941 (2026-11-25 10:50Z, 218k views, 3.2k likes, 3.4k bookmarks). List: DeepSeek V4.1 Flash 1017 Uncensored, GLM-5.3 Uncensored, Inkling 2 Mini Uncensored, Qwen3.8-27B Abliterated, Qwen3.8-Flash-Next Abliterated, GLM-5.3 Flash Uncensored, Hy4 Flash Uncensored, DeepSeek V4 Pro Qwen3.5 9B Heretic, Gemma 4 31B Heretic, Venice Uncensored 1.2. No links in the post (ends with "links:"); author replies "you can also use API, will share API providers soon" and "mostly yes" to "is this local llm?". One reply says they do not work like uncensored.
- Why it matters: our persona is profanity-heavy and insulting — an abliterated model (esp. Qwen3.8-27B, a family Groq already serves) could reduce refusals/lecturing on insult prompts. Why not actionable: no provider links, mostly local HF weights needing GPU, and none of our free providers (Groq/Gemini/NVIDIA) serve abliterated variants; OpenRouter (which might) has our key rejected. Next step if pursued: check whether any free OpenAI-compatible provider serves an abliterated Qwen3-8-27B. Do not adopt now.

## 5. @danikkk_wqs — Claude token cut 150k→2k — NOT useful
- Post: https://x.com/danikkk_wqs/status/2125562246738608337 (2026-11-25 12:08Z, 59k views, 374 likes, 1k bookmarks). Anthropic engineers' method for cutting Claude context 98.7% by having Claude write code that calls tools instead of calling them one by one (tools as files, load on demand, filter before reading, loops in code, PII masking, save working code as skills).
- Claude Code agent workflow, not bot runtime. Our bot is a single-process Telegram bot with a fixed router, not a Claude Code session. Nothing to apply.

## 6. @0xclayo — 13 repos for files/vectors/memory — NOT useful now
- Post: https://x.com/0xclayo/status/2125586628018053493 (2026-11-25 13:45Z, 1.7k views, 26 likes, 37 bookmarks). 13 GitHub repos for document/RAG/memory work in Claude: MarkItDown, MinerU, Docling, LlamaIndex, Milvus, LightRAG, GraphRAG, Qdrant, Cognee, Graphiti, Letta, pgvector, LanceDB.
- RAG over Bahgat transcripts is a deferred item, and all of these are heavyweight infra (vector DBs, graph RAG) that do not fit Render free 512 MB. Our SQLite per-member memory is sufficient. Future reference only if RAG is ever built.

## 7. @Dionisselamii — 5 skills that kill AI slop — NOT useful
- Post: https://x.com/Dionisselamii/status/2125608317187682479 (2026-11-25 15:11Z, 29k views, 557 likes, 871 bookmarks). Five design skills for Claude Code (ThinkUI, Anti UI Slop, Taste Skill, Emil Design Engineering, Vercel Web Design Guidelines).
- UI/design skills for web apps. Our bot has no UI. Nothing to apply.

## 8. @rosemoni18 — 10 repos for an AI content factory — NOT useful
- Post: https://x.com/rosemoni18/status/2125493578080334173 (2026-11-25 07:35Z, 4k views, 139 likes, 97 bookmarks). Ten open-source repos: OpenCreator, Social Media Research Skills, Local Deep Research, FLUX.2, Kokoro (TTS), ACE-Step 1.5 (music), Short Video Factory, AI YouTube Shorts Generator, Podcastfy, Social Media Agent.
- Content-creation tooling (video/music/images), not Telegram bot components. Kokoro is a fixed-voice TTS (no voice cloning) needing local inference — a possible future TTS alternative to Edge TTS at most, and too heavy for Render free.

## 9. @0xCodila profile — NOT useful
- Profile: https://x.com/0xCodila — codila, verified, 38k followers, 2.5k posts, bio "AI - researcher & software engineer | writing about what I use myself". Recent posts (fetched 2026-11-25) are all about one topic: a Gemini 4 Neon + Antigravity agent-engineering course (agent teams, swarms, graphs, "150+ Google agent skills"). Earlier known threads: BLA (anti-reverse-engineering for shipped apps), GrokBot agent teams, Jev routing layer.
- None of it fits a 15-user, free-tier, single-process Telegram bot: Antigravity/Claude Code agent teams are a different (paid/Google) ecosystem; BLA protects shipped apps; Jev adds an API dependency for routing our small rule-based router already handles. Worth following for general AI-agent news only.

## Sources
- x-scout: https://github.com/JunJayDev/x-scout (read path needs no key; search needs a Grok key, not used)
- VoiceStudio repo: https://github.com/debpalash/VoiceStudio ; engine catalog: https://github.com/debpalash/VoiceStudio/blob/HEAD/docs/engines/README.md
- All post URLs are listed in the sections above.
