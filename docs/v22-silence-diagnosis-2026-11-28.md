# v2.2 live silence — diagnosis (2026-11-28 ~07:40 EET, research stage)

## Symptom
v2.2 deployed to Cloady and went live ~05:14 UTC (07:14 EET). Live test:
**0 replies to 12 test messages.** The bot is not answering anything.

## Likely root cause: stale `messages` table on the persistent volume
The live container reuses the old `bahgat.db` from v1.x on the persistent
`/app/data` volume — and v2.2 changed the `messages` columns without any
migration.

v1.17 (the version live before v2.2; v1.18 was never deployed) —
`memory/schema.sql`, same file `data/bahgat.db`, same `BAHGAT_DATA_DIR`:

```sql
CREATE TABLE IF NOT EXISTS messages (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  chat_id INTEGER,
  user_id INTEGER,
  role TEXT,
  text TEXT,
  created_at REAL
);
```

v2.2 — `bahgat/db.py`, `_SCHEMA`:

```sql
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id INTEGER NOT NULL,
    author TEXT NOT NULL,
    text TEXT NOT NULL,
    ts REAL NOT NULL
);
```

`init_db()` only runs `CREATE TABLE IF NOT EXISTS`, so against the existing
old table it is a no-op — the old schema survives. There is no schema
version table and no migration anywhere in `bahgat/`.

## Failure chain (every message, total silence)
1. `handle_message` (`bahgat/handlers/chat.py`) calls
   `db.add_message(chat_id, user_name, ...)` **before any branch** —
   even before the identity-denial branch.
2. `add_message` runs
   `INSERT INTO messages (chat_id, author, text, ts) VALUES (?,?,?,?)`
   against the old table → `sqlite3.OperationalError: no such column: author`.
3. The exception escapes the handler; `_error_handler` in `bahgat/app.py`
   only logs it and never sends anything. Cloady shows no runtime logs
   (v1.8 note), so the failure is invisible from the outside.
4. `recent_messages` (`SELECT author, text ...`) and `recent_bot_replies`
   (`... WHERE author='bot'`) would fail the same way, so no code path
   can produce a reply. An LLM outage cannot explain this: `generate_reply`
   falls back to a bank line and still sends — the crash happens before
   the LLM is ever reached.

## Checked and ruled out (from the local repo, commit 8ce7718)
- Trigger words: `TRIGGER_WORDS = ("بهجوتي", "بهجت")` in `bahgat/persona.py`
  — "يا بهجت" matches. The comma is not the cause.
- Env vars: names identical v1.17/v1.18 → v2.2 (`TELEGRAM_BOT_TOKEN`,
  `OWNER_ID`, `GROQ_API_KEY`, `NVIDIA_API_KEY`, `GEMINI_API_KEY`), so a
  missing-env crash loop on startup is unlikely.
- Handler registration: `MessageHandler(filters.TEXT & ~filters.COMMAND,
  chat.handle_message)` — group text passes.
- Health server: `OSError` on bind is caught, returns None, never crashes.
- LLM client failure: caught (`LLMError`) in `post_init`, bot still runs.
- Privacy mode: plain "يا بهجت" trigger messages got replies in v1.x live
  tests (`docs/live-test-matrix.md`), so update delivery to the bot works.

## One-command verification on the Cloady host
```sh
sqlite3 /app/data/bahgat.db ".schema messages"
```
If it shows `user_id, role, created_at` → hypothesis confirmed. If it
shows `author, ts` → the volume was wiped on redeploy and the cause is
elsewhere (next candidates: deploy did not pick up the new image, or a
second old poller still holding the getUpdates session → Telegram 409).

## Fix (needs Seif's go + push + redeploy)
In `bahgat/db.py::init_db`, migrate when the old shape is detected —
standard SQLite pattern, no new dependency:

```python
cols = {r[1] for r in c.execute("PRAGMA table_info(messages)")}
if cols and "author" not in cols:
    c.execute("ALTER TABLE messages RENAME TO messages_v1")
    # then run the CREATE TABLE for the new shape (already in _SCHEMA)
```

Alternative with zero code: delete `bahgat.db` on the host. Loss is
trivial — v2.2 keeps no member data in it (`targets.py` cache is
in-memory; `messages` is only recent context + anti-repeat).

Regression test to add (`tests/test_db.py` currently has no legacy case —
that is why 214 green tests missed this): build a DB with the v1.x
`messages` schema, run `init_db`, then `add_message` + `recent_messages`
must succeed.

## Status
Diagnosis only — nothing applied, nothing pushed, nothing deployed.
The Colab voice training and the v2.2 live-test follow-ups in the main
chat are separate live threads; this note is only about the silence.

**Update 07:44 EET:** fix implemented in `bahgat/db.py` (migration
preserving rows, not the rename-and-drop sketch above) + regression test
`test_migrates_v1_messages_table` in `tests/test_db.py`; verified locally
(215 passed + 1 known env fail, ruff clean; old-schema repro now passes
`add_message`). See CHANGELOG v2.2.1. Awaiting the owner's go to push.
