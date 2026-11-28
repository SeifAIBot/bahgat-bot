# Architecture — Bahgat Bot (v0.5, as built)

Short and true. Anything here you cannot find in the code is a gap, not a
feature — the known gaps are listed at the bottom.

## Principles
- Handlers route; `brain/` decides; `tools/` execute. `main.py` only wires
  things up. Config in YAML + `.env`, never hardcoded.
- Guardrails live in code, not in the prompt (insult rules, injection
  stripping, post-checks). Secrets only in `.env` / Render env vars.
- One file per concern. Logging from day one, not `print()`.

## Layers (actual call path)
```
Telegram update
  -> tg/handlers.py (routing, trigger gate, owner commands, allowlist, quota,
                     per-chat lock, typing renewal, YouTube callbacks, /stats)
  -> brain/intent.py (search / youtube / voice / just_chat from normal talk)
  -> brain/memory.py (per-member + per-group memory, SQLite; quota, kv state,
                      YouTube file-id cache, format_history)
  -> brain/mood.py (mood 0-100, voice policy)
  -> brain/prompt.py (system prompt v5 + user-role memory block)
  -> brain/router.py (Groq first, Gemini reserved; caps enforced before calls)
  -> brain/verify.py (post-check: family insults, banned phrases, leakage)
  -> tools/search.py (DuckDuckGo + parallel page fetch)
  -> tools/youtube.py (yt-dlp, resolve first, 50 MB limit)
  -> tools/voice.py (Edge TTS -> ogg voice note)
  -> tg sender (text first, then voice if policy says so)
```

## Data
- SQLite (WAL) for v1. Tables in `memory/schema.sql`: members, messages,
  processed_updates, provider_usage, pinned_facts, outbox, daily_usage,
  bot_state, youtube_files.
- `pinned_facts` and `outbox` tables exist but nothing reads or writes them
  yet — there is no outbox sweeper and no pinned-facts feature. Do not build
  on them until one lands.
- No secrets in DB. Tokens only in `.env` / Secure Vault / Render env vars.
- Vector / RAG for Bahgat examples is v2 (FAISS, local embeddings) — v1 uses
  few-shot examples from `persona/bahgat/examples.md`.

## Config (actually honoured)
- `config/persona.yaml` — persona text, mood thresholds, voice rules; read at
  startup and on owner `/reload`.
- `config/providers.yaml` — provider order/models, daily caps, output-token
  caps; read once by the router at startup (changing it needs a restart).
- `config/rules.yaml` — owner-only command list, parody bio text. The owner id
  lives ONLY in env (`OWNER_ID`); it was removed from this file.
## Plugins — removed as dead code (v1.15-simplified)
- The `plugins/` package and `config/plugins.yaml` were deleted: nothing
  ever called the registry and no plugin implemented a shared interface.
  The pipeline calls `tools/*` directly from `tg/handlers.py`.
- To add a plugin system for real, implement one Protocol, a dispatcher,
  and one test per plugin — do not resurrect the deleted stub files.

## Known gaps (do not mistake for features)
- No `services/` layer: `tg/handlers.py` still orchestrates the pipeline and
  contains some SQL (dedup, stats, purge). Extracting a service layer is
  future work.
- No single-instance guard beyond `render.yaml` `numInstances: 1`: never run
  a local copy and the Render worker with the same token (second poller gets
  409 Conflict and steals updates).
- Render Free has no persistent disk: `data/bahgat.db` is wiped on every
  redeploy/restart, so memory/mood/grudge/quota reset. See `docs/DEPLOY.md`.
- No migrations: schema is `CREATE TABLE IF NOT EXISTS` at startup
  (`init_db()`), no version table.
- No CI coverage gate yet (CI runs ruff + pytest); handler coverage is the
  v0.5 suite in `tests/test_handlers_v5.py`.

## Updates
- Persona / mood / rules: edit YAML, owner sends `/reload` (or "ريلود"), no redeploy.
- Provider change: edit `config/providers.yaml`, restart.
- Version + CHANGELOG in `docs/CHANGELOG.md` for every change.
