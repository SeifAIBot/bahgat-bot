# Bahgat Bot

Telegram group bot: an Egyptian-dialect character in the style of the
streamer Bahgat Saber — impulsive, funny, sarcastic, in Egyptian dialect.
The Telegram account is labelled a bot in its bio ("بوت مصري بيهزر،
وفخور إنه بوت."), and Telegram shows the official "Bot" tag; in chat he
never admits he is a bot — he answers as a normal human. **That is the
owner's explicit call (2026-11-28), and it is a known conflict with
Telegram Bot Terms §5.2(c)-(d) on impersonation/misrepresentation —
see CHANGELOG.md.**

**Not affiliated with, endorsed by, or representing the real Bahgat Saber.**

## What it does

- Replies in a group only when @mentioned, addressed by name (بهجت /
  بهجوتي), or replied to.
- Chats in Egyptian dialect: short, impulsive, sarcastic, self-deprecating.
- Web search (DuckDuckGo, no key) with numbered sources.
- Songs/videos: YouTube search + metadata always; **one plain download
  attempt** (current yt-dlp + PO-token provider; optional egress proxy via
  `YTDLP_PROXY_URL`) — if the host's IP is blocked it says so in
  character, hands over the link, and offers matches from permitted open
  sources (Internet Archive / SoundCloud / Audius), clearly labelled as
  different catalogues, not the same song.
- Voice notes with a **generic TTS voice** (Edge TTS `ar-EG-ShakirNeural`)
  by default; when `RVC_URL` points at a separate RVC worker, the voice
  note is converted into the character's voice there, with Edge TTS as
  the automatic fallback. RVC never runs inside this container.
- `/about` — in character (no parody admission in chat).
- `/stats` — owner-only LLM stats (success rate, p50/p95 latency,
  fallbacks, bank fallbacks).

## LLM providers

One bot, several providers, tried in order. `config/providers.yaml` lists
the chain (Groq 20b → Groq 120b → Groq qwen3.8-27b → Gemini 3.5-flash-lite
→ NVIDIA Nemotron); `bahgat/llm.py` walks it and returns the first usable
answer. A network error, timeout, rate limit (429), 5xx or a filtered
answer moves on to the next provider; a 401/403/404 (dead key, retired
model) drops that entry for the rest of the run, and a provider that fails
twice in a row is cooled down for 10 minutes. One retry only, for
429/5xx/timeout, honouring Retry-After. Each entry carries its own
15 s timeout and the turn budget is ~30 s, so no turn hangs for minutes.

Fill a key for every provider you have; providers without a key are simply
left out of the chain, and the bot needs at least one. There is no quota
tracking, fair-share or telemetry database: the chain is the capacity
plan, plus minimal counters (see /stats).

To change the order, edit the file. `LLM_CHAIN=groq-120b,gemini-3.5-flash-lite`
overrides the order for one deployment, `LLM_PROVIDER=gemini` moves a family
to the front (the rest still backs it up), and `LLM_MODEL` / `LLM_BASE_URL` /
`LLM_API_KEY` retarget only the first entry.

## Hard rules (enforced in code, `bahgat/rules.py`)

- Insults are target-aware: at group members, person-only — never
  parents, family or relatives. At non-members (resolved via reply /
  @mention / getChatMember, fail-safe = member) and at named public
  figures, the full range is allowed, including family insults.
- The bank loader serves `member_safe: false` lines ONLY for a
  positively resolved non-member target; a per-reply gate rejects any
  reply carrying a family insult when the target is a member.
- No slurs on religion, ethnicity, nationality or sect.
- No sexual harassment. No real threats or incitement to harm.
- Public figures may be roasted by name. Messi is defended, never
  roasted; Sisi is insulted directly.
- The owner is never insulted.
- The bot never admits he is a bot (owner decision; see the note at the
  top of this file).

## Setup

```bash
python -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env   # fill TELEGRAM_BOT_TOKEN, OWNER_ID and your LLM keys
.venv/bin/python main.py
```

`ffmpeg` must be installed for voice notes. Env vars (see `.env.example`):

| Var | Required | Purpose |
| --- | --- | --- |
| `TELEGRAM_BOT_TOKEN` | yes | BotFather token |
| `OWNER_ID` | yes | owner's numeric Telegram ID (never insulted) |
| `GROQ_API_KEY` | one of these | Groq key — three models in the chain |
| `NVIDIA_API_KEY` | one of these | NVIDIA NIM key (trial terms: evaluation only) |
| `GEMINI_API_KEY` | one of these | Google AI Studio key — gemini-3.5-flash-lite |
| `LLM_CHAIN` | no | comma-separated entry/family names — overrides the chain order |
| `LLM_PROVIDER` / `LLM_MODEL` / `LLM_BASE_URL` / `LLM_API_KEY` | no | move a family to the front / retarget the first entry |
| `RVC_URL` | no | base URL of the separate RVC worker (empty = Edge TTS only) |
| `YTDLP_PROXY_URL` | no | egress proxy for yt-dlp, e.g. WARP wireproxy (empty = direct) |
| `YT_DLP_POT_PROVIDER_URL` | no | remote bgutil PO-token server (empty = local provider) |
| `ALLOWED_CHAT_IDS` | no | comma-separated chat allowlist (empty = any group) |
| `BAHGAT_DATA_DIR` | no | runtime state dir (default `./data`) |
| `DROP_PENDING_UPDATES` | no | default `true` |
| `PORT` | no | `/healthz` port (default 8080) |

## Deploy

Any always-on host works. With Docker: `docker build -t bahgat-bot . &&
docker run --env-file .env -v bahgat-data:/app/data bahgat-bot`.
On a PaaS set `BAHGAT_DATA_DIR` to the persistent volume and `PORT` as
injected; `/healthz` answers health checks.

## Tests

```bash
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest tests/ -q
.venv/bin/python -m ruff check .
```

## Layout

```
main.py            entry point (logging + polling)
bahgat/
  config.py        env settings (incl. RVC_URL, YTDLP_PROXY_URL)
  persona.py       the short stable system prompt, bio, in-character about
  rules.py         red lines enforced in code on every reply
  targets.py       target resolution (reply / @mention / sender) + membership
  stats.py         minimal counters (LLM calls, fallbacks, bank fallbacks)
  llm.py           LLM client: ordered multi-provider fallback chain
  reply_bank.py    curated line bank loader + serving filter + no-repeat
  media.py         YouTube (search/metadata/one download) + open-source fallback
  search.py        DuckDuckGo web search + page fetch (SSRF-guarded)
  voice.py         Edge TTS voice notes + RVC-worker seam (send_voice)
  db.py            SQLite: recent messages + served-line window
  health.py        /healthz endpoint
  handlers/
    chat.py        routing + LLM conversation + /stats (owner-only)
    media.py       song/video flow
    voice.py       voice-note flow
config/
  providers.yaml   the LLM chain: entries, models, key env vars, timeouts
persona/
  examples.md      few-shot style pairs (part of the system prompt)
  reply_bank.yaml  curated lines (filtered at load: no family/religion/
                   sexual/threat lines are served at members)
tests/             pytest suite (no network, no real LLM)
docs/live-test-log.md  live-test criteria + session log
```

Feature set is frozen at v2.2 (see CHANGELOG.md).
