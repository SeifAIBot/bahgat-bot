# Changelog

## v2.2 — 2026-11-28 — Instinct base aligned to owner vision

This is Instinct's v2.1 rewrite adopted as the new base and aligned to the
owner's decisions (expert review 2026-11-28:
`research_notes/bahgat-instinct-adaptation-expert-review-20261128-0409/`).
Pre-v2.0 history (v1.0–v1.18) lives in git history under tag **v1.18**.

Identity (owner decision 2026-11-28, overrides the v2.1 honest answer):
- Bahgat NEVER admits he is a bot in chat. An identity question gets the
  deterministic in-character denial "أنا بهجت يا عم، إنسان عادي، مش بوت."
  (no LLM call), and `rules.check_reply` replaces any self-admission in a
  generated reply with the same denial. `/about` is in character.
- The account bio still labels it a bot ("بوت مصري بيهزر، وفخور إنه بوت.")
  and Telegram shows the official "Bot" tag.
- **Known compliance risk (recorded, not re-litigated):** the never-admit
  rule conflicts with Telegram Bot Terms §5.2(c)-(d)
  (impersonation/misrepresentation). The experts recommended an
  in-character deflection acknowledging the bot label on direct identity
  questions; the owner chose to keep never-admit, with the bio disclosure
  staying prominent.

Family insults — target-aware (owner rule; fixes the live W.W.3 failure
where "كسمك" reached a member):
- `bahgat/targets.py`: `resolve_target()` (reply-to > TEXT_MENTION >
  @mention-cache > sender) + `is_member()` via getChatMember, fail-safe
  unknown = member, 5-minute cache. Named public figures are non-members
  by definition.
- The bank serves `member_safe: false` lines ONLY for a positively
  resolved non-member; a per-reply gate `rules.allowed(text, is_member)`
  runs once before sending, using normalised token/phrase matching
  anchored on كس with an allow-list checked first (ابن خلدون، أم كلثوم،
  أم الدنيا). Regression tests: كسمك / كس امك / كس أمك (with diacritics
  and tatweel) are caught; the allow-list is never flagged.

Public figures: the roast ban is deleted. Sisi is insulted directly (no
debate); Messi is defended, never roasted (the bank pick is skipped and
the turn goes to the LLM with a defence note); Salah, Amr Diab and Tamer
Hosny are mocked freely.

Persona: one compact OPINIONS block in the system prompt from the
owner-approved facts (Ahly + board, national team, Salah, Messi, Vinícius /
Rodrygo, béchamel + mahshi, boftik / cooked veg / fesikh, Palestine /
Jerusalem / Israel, Saudi Arabia + Morocco, Android vs iPhone/Mac, army +
police, Amr Diab + Tamer Hosny, Abo Treika). No 51-row facts system.

Provider chain (expert §1; owner rule — Cerebras + OpenRouter are OUT):
`groq-20b` → `groq-120b` → `groq-qwen` → `gemini-3.5-flash-lite` →
`nvidia-nemotron`. Removed: Cerebras, OpenRouter, gemma-4-31b-it,
gemini-3.1-flash-lite, gemini-3-flash-preview. Per-attempt timeout 15 s
(NVIDIA 20 s), total turn budget ~30 s, 0–1 retry only for 429/5xx/timeout
honouring Retry-After; 401/403/404 drop the entry for the run; a provider
that fails twice in a row is cooled down for 10 minutes. Empty completion
and Gemini SAFETY finishReason count as failures → next provider, then
the bank fallback.

Voice (RVC track KEPT, separate worker later — never embedded in the
1 GB container): `voice.send_voice()` tries the RVC worker first when
`RVC_URL` is set (POST /convert, index_rate 0.75, 90 s timeout) and falls
back to Edge TTS on ANY failure. RVC_URL unset = Edge TTS only.

Observability (minimal, expert §5): `bahgat/stats.py` — ~30 lines stdlib:
per-provider counts, success rate, p50/p95, failure breakdown, cooldown
state, fallback + bank-fallback counters; one JSON log line per LLM call;
owner-only `/stats`. No Prometheus, no quota system.

YouTube: yt-dlp floor 2026.11.23 + `bgutil-ytdlp-pot-provider==2.0.2`
(PO tokens); `YTDLP_PROXY_URL` routes yt-dlp through an egress proxy
(e.g. a WARP wireproxy) when set, non-fatal when unset; the open-source
fallback is labelled as a different catalogue, not the same song.

Not brought back from v1: quota/fair-share, telemetry DB, mood engine,
persona-fact injection, deep router, /diag, the WARP subsystem (the
proxy env var is the seam for it later).

Tests: ~200 tests (164 baseline + new coverage for target resolution,
family matcher + allow-list, identity denial, chain order/failover/
cooldown, /stats owner-gating, RVC fallback, proxy/POT env). Full suite
passes; ruff clean.

## v2.1.0 — 2026-11-28 — multi-provider LLM chain restored

Owner decision: keep the original models, do not run on a single model. The
one-provider registry from v2.0 is replaced by an ordered fallback chain,
without bringing back the v1 quota/fair-share/telemetry machinery.

LLM:
- `config/providers.yaml` lists the chain in try order: Groq
  (`openai/gpt-oss-20b`, `openai/gpt-oss-120b`, `qwen/qwen3.8-27b`),
  Cerebras (`gpt-oss-120b`), NVIDIA (`nvidia/nemotron-3.5-super-vl-120b-a12b`),
  Gemini (`gemini-3.5-flash-lite`, `gemini-3.1-flash-lite`, `gemma-4-31b-it`,
  `gemini-3-flash-preview`) and OpenRouter (`google/gemma-4-31b-it:free`,
  `nvidia/nemotron-3-super:free`). Models, base URLs and order are copied
  from the v1.17 `config/providers.yaml`; the file is the single place to
  edit them.
- `bahgat/llm.py` walks the chain: the first usable answer wins. Network
  error, timeout, rate limit, empty completion or a filtered answer
  (`content_filter` / `SAFETY`) moves to the next entry; 401/403/404 drops
  the entry for the rest of the run. One attempt per entry (`max_retries=0`
  on the SDK client) with a per-entry timeout (20 s Groq/Cerebras, 30 s the
  rest), so a dead provider costs one timeout, not a hung turn.
- Keys are env vars, one per provider (`GROQ_API_KEY`, `CEREBRAS_API_KEY`,
  `NVIDIA_API_KEY`, `GEMINI_API_KEY`, `OPENROUTER_API_KEY`); providers with
  no key are skipped at startup. Keys are read from `.env` through Settings
  first, then the process environment — the v2.0 code only read the process
  environment, so a key that lived only in `.env` did not reach the client.
- Optional overrides: `LLM_CHAIN` sets the order, `LLM_PROVIDER` moves a
  family to the front without removing the rest, and
  `LLM_MODEL` / `LLM_BASE_URL` / `LLM_API_KEY` retarget only the first entry.
- No quota tracking, fair-share, circuit-breaker, telemetry or usage tables.
  Error logs name the provider and HTTP status only, never a key.
- Unchanged from v2.0: parody labelling, the honest answer to a sincere
  "are you a bot?", reply filters, YouTube without WARP/cookies plus the
  permitted-source fallback, generic TTS, the short stable prompt, and the
  anti-repeat guard.

Tests: `tests/test_llm.py` covers the config, key resolution and overrides;
`tests/test_llm_fallback.py` covers the chain with mocked providers
(order, failover, empty/refusal, 401/403/404 disabling, total failure,
no key in error text). 165 tests pass.

## v2.0.0 — 2026-11-28 — simplification rewrite

Full rewrite of v1.17 by deletion, after the 2026-11-28 W.W.3 live session
exposed repetition, evasive answers, a family insult at a member, identity
flip-flop, and broken media routing. The old 11.6k-line codebase (router
rotation, quota/fairshare, telemetry, mood engine, persona-fact injection,
WARP tunnel, cookies workarounds, plugin skeleton) is replaced by ~2k
lines. Feature set is FROZEN here — new features need an explicit owner
decision.

Persona & safety:
- Clearly labelled **unofficial parody** of Bahgat Saber: bio, `/about`
  and disclaimer say so; a sincere "are you a bot / the real person?" is
  answered honestly (was: "never admit you are a bot", now removed as a
  pass criterion).
- Never states facts or political positions as the real person's; no
  incitement, threats or calls to harm.
- Insults target the provoking person (or the bot itself) only. No family
  insults for anyone (was: allowed against non-members). No religion/
  ethnicity slurs, no sexual harassment, no abuse of real named public
  figures. Enforced in code (`bahgat/rules.py`) on every reply, plus a
  load-time filter on the reply bank (`bahgat/reply_bank.py`).
- Short stable system prompt + few-shot examples; removed the per-turn
  "you asked this before" and deep-note injections; user text and search
  results are wrapped as data; a reply that leaks the prompt is rejected.

Media:
- YouTube: WARP tunnel, re-registration and cookie workarounds REMOVED.
  One plain download attempt; on failure an in-character reply with the
  link + fallback search of permitted sources (Internet Archive,
  SoundCloud, Audius). YouTube search/metadata unchanged.
- Voice notes use a generic Edge TTS voice. The RVC/GPT-SoVITS
  voice-cloning track is dropped.

Engine:
- One LLM provider (Groq) behind a tiny registry (`bahgat/llm.py`) instead
  of the multi-provider rotation, quota, fairshare, circuit-breaker and
  cache machinery.
- Anti-repeat guard (regenerate once, else a bank line) against the
  repeated-lines defect seen live.
- `tg/handlers.py` (3,771 lines) split into `handlers/chat.py`,
  `handlers/media.py`, `handlers/voice.py`.
- New focused test suite replaces the old 946-test suite tied to deleted
  machinery.

## v1.17 and earlier

Pre-rewrite history lived in docs/CHANGELOG.md of the old tree and was
removed with the old code. Live-test findings that motivated this rewrite
are preserved in docs/live-test-log.md.
