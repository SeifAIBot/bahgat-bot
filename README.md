# بهجت — Telegram Group Bot

Parody / fan roleplay bot for Telegram groups. Named **بهجت**, styled after Bahgat Saber: impulsive, says what's on his mind, swears a lot, funny, Egyptian dialect only. It is **not** the real Bahgat Saber.

## What it does (v1)
- Replies in groups only when mentioned, when someone says "بهجت", or when someone replies to its message.
- Understands normal Egyptian talk — no slash commands. It decides itself if a request needs web search, YouTube, or voice.
- Personal assistant in the group: web search (opens pages, summarises in Arabic), YouTube video or audio-only, voice notes.
- Memory per member, mood that changes with what is said to it. If insulted, it gets angry and answers back like Bahgat — it does not laugh it off.
- Owner-only control: only Seif (OWNER_ID) can control it, not any group admin.
- Text first. Voice only when asked, when very angry, at random times, or when the topic is interesting.
- If it does not know an answer, it searches the web first — it never says "مش عارف" and stops.
- All replies in Bahgat's style, Egyptian dialect only, never Fusha, never generic AI phrases.

## Insult rules (enforced in code, not just prompt)
- Group member target: insult the person only. No father, mother, or family.
- Non-member / fictional / public figure target: full freedom.
- Owner (Seif) target: never insulted, ever.
- Implemented in `tg/handlers.py`: the bot resolves the real insult target
  (reply-to / @mention / named target matched against recent speakers) and
  checks membership with `get_chat_member` (cached 10 min) before choosing
  the level; the level is passed into the system prompt AND the post-check
  in `brain/verify.py`.

## Architecture — built for frequent updates
Config-driven: handlers route, `brain/` decides, `tools/` execute.
See `docs/ARCHITECTURE.md`. (`plugins/` exists but is a stub — its registry
is never called from the pipeline; see ARCHITECTURE.md.)

```
config/     persona.yaml, providers.yaml, rules.yaml — change behaviour without touching code
core/       config loading, logging, errors, rules
tg/         handlers only (routing) — no business logic here
brain/      LLM router (multi-provider fallback), intent, memory, mood
tools/      search, youtube, voice — each tool is swappable
plugins/    stub, not wired into the pipeline yet (see docs/ARCHITECTURE.md)
persona/    Bahgat style examples, catchphrases, mood triggers
memory/     SQLite schema, per-member / per-group memory
```

Update policy:
- Change persona/mood/rules → edit a YAML file, no code change, reload with `/reload` (owner only) or restart. (`/reload` re-reads `persona.yaml`, `examples.md`, `rules.yaml`; changing `providers.yaml` still needs a restart — the router reads it once at startup.)
- Add a capability → currently a new function in `tools/` + a branch in `tg/handlers.py` + tests. (`plugins/` is not wired into the pipeline yet, so "new plugin folder + 1 line in config" does not work today.)
- Change LLM provider/order → edit `config/providers.yaml` only, then restart.
- Never hardcode tokens. All secrets in `.env` (see `.env.example`).
- Every change gets a CHANGELOG entry and a test in `tests/`.

## Free stack
- Telegram Bot API — free
- LLM: Groq first (gpt-oss-120b/20b, free tier) for everything; Gemini
  (gemini-3-flash-preview) reserved for hard/search turns. Daily caps are
  enforced in code before calling: Groq 150,000 tokens/day, Gemini 15
  requests/day (see `/stats`, owner only). OpenRouter was removed in v0.4 —
  no key was ever requested for it, so it never ran as a fallback.
- Search: DuckDuckGo / Brave free search, page fetch + summarise.
- YouTube: yt-dlp + ffmpeg, video (480p) or audio (mp3), Telegram 50 MB bot limit.
- Voice: Edge TTS (free, Egyptian Arabic) first. RVC / GPT-SoVITS voice conversion to Bahgat's voice is a separate, later step — see `docs/voice-plan.md`. Exact 100% voice match is not promised.

## Run (local test)
```bash
cp .env.example .env   # fill TELEGRAM_BOT_TOKEN, OWNER_ID, GEMINI_API_KEY, GROQ_API_KEY
pip install -r requirements.txt
python main.py
```

## Deploy (free)
Render Free tier for v1. Oracle Always Free VPS if the group gets big. See `docs/DEPLOY.md`.

## Privacy — where group data goes
- Voice: Edge TTS is an unofficial, reverse-engineered Microsoft endpoint —
  the text being voiced is sent to Microsoft. There is no official Azure
  Speech key; if it blocks the bot, voice falls back to text.
- Search: DuckDuckGo HTML scraping (spoofed browser User-Agent) + direct
  page fetches. Fetched pages are treated as untrusted data, never as
  instructions.
- Storage: everything is SQLite (`data/bahgat.db`, WAL) on the host — members
  (name, mood, notes, grudge), recent messages (last 200/chat), daily quota
  counts, YouTube file-id cache. No vector DB, no external analytics.
- Retention: `processed_updates` rows older than 48h are pruned at startup;
  the bot deletes a chat's messages from the DB when it is removed from that
  group; the owner can clear a member's memory with "امسح ذاكرة [name]".
  Note the Render Free caveat in `docs/DEPLOY.md`: the DB file is wiped on
  redeploy/restart, so memory/quota reset.
- The bot's bio and its first message in a new group both say it is a
  parody bot, not the real Bahgat Saber.

## Status
- Scaffold: done
- Token verified: @Bahgoti_bot, id 9106462211 (getMe, 2026-11-25)
- Owner ID verified: 1415214630 (Seif)
- Test group: invite link known (https://t.me/+RN2Fksh8-KU3NWI0); numeric
  chat id not known yet — set `ALLOWED_CHAT_IDS` to it once known
- Still waiting: Seif adding @Bahgoti_bot as admin to the test group
  (privacy mode is ON, so plain "بهجت" messages are only delivered if the
  bot is admin or privacy mode is disabled in BotFather)
- Voice training dataset: see `docs/training-videos.md` — audio cleanliness NOT yet verified by listening
- Not yet tested in a group. Do not deploy to the main group before private-group testing.
