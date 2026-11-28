"""Minimal SQLite state: recent chat messages (context + anti-repeat) and
recently served reply-bank lines (no-repeat window). Nothing else.

The old project's quota/fairshare/telemetry/cache/grudge tables are gone —
deleted on purpose in the v2.0 simplification.
"""
import sqlite3
import time
from pathlib import Path

from bahgat.config import data_dir

_SCHEMA = """
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id INTEGER NOT NULL,
    author TEXT NOT NULL,          -- display name, or "bot" for our replies
    text TEXT NOT NULL,
    ts REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_messages_chat ON messages(chat_id, id);
CREATE TABLE IF NOT EXISTS used_lines (
    chat_id INTEGER NOT NULL,
    line_id TEXT NOT NULL,
    ts REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_used_lines ON used_lines(chat_id, line_id);
"""

_KEEP_MESSAGES_PER_CHAT = 50
_KEEP_LINE_WINDOW = 25


def _db_path() -> Path:
    d = data_dir()
    d.mkdir(parents=True, exist_ok=True)
    return d / "bahgat.db"


def _conn():
    c = sqlite3.connect(_db_path(), timeout=10)
    c.execute("PRAGMA journal_mode=WAL")
    return c


def _migrate_messages_table(c) -> None:
    """v1.x -> v2.2: the old messages table (user_id/role/created_at) shares
    the bahgat.db filename on the persistent volume, so CREATE TABLE IF NOT
    EXISTS silently keeps it — and every add_message then dies with
    "no column named author", silencing the bot entirely (live 2026-11-28:
    app Running, zero replies, not even to an @mention). Migrate it with
    SQLite's documented rename pattern, preserving rows (role -> author,
    created_at -> ts). Idempotent: a new-schema table is left alone."""
    cols = {r[1] for r in c.execute("PRAGMA table_info(messages)")}
    if not cols:
        return  # no table yet — the schema script below creates it
    if "author" in cols and "ts" in cols:
        return  # already the new shape
    if "role" not in cols or "created_at" not in cols:
        # Unknown shape — drop it rather than crash every message.
        c.execute("DROP TABLE messages")
        return
    c.execute("""
        CREATE TABLE messages_new (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER NOT NULL,
            author TEXT NOT NULL,
            text TEXT NOT NULL,
            ts REAL NOT NULL
        )""")
    c.execute("""
        INSERT INTO messages_new (id, chat_id, author, text, ts)
        SELECT id, chat_id, COALESCE(role, 'user'), text,
               COALESCE(created_at, 0)
        FROM messages""")
    c.execute("DROP TABLE messages")
    c.execute("ALTER TABLE messages_new RENAME TO messages")


def init_db(db_path=None) -> None:
    path = Path(db_path) if db_path else _db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(path, timeout=10)
    try:
        _migrate_messages_table(c)
        c.executescript(_SCHEMA)
        c.commit()
    finally:
        c.close()


def add_message(chat_id: int, author: str, text: str) -> None:
    c = _conn()
    try:
        c.execute("INSERT INTO messages (chat_id, author, text, ts) VALUES (?,?,?,?)",
                  (chat_id, author, text[:2000], time.time()))
        # Keep only the newest N per chat.
        c.execute(
            "DELETE FROM messages WHERE chat_id=? AND id NOT IN "
            "(SELECT id FROM messages WHERE chat_id=? ORDER BY id DESC LIMIT ?)",
            (chat_id, chat_id, _KEEP_MESSAGES_PER_CHAT),
        )
        c.commit()
    finally:
        c.close()


def recent_messages(chat_id: int, limit: int = 10) -> list:
    """Oldest-first list of {"author", "text"} for conversation context."""
    c = _conn()
    try:
        rows = c.execute(
            "SELECT author, text FROM messages WHERE chat_id=? ORDER BY id DESC LIMIT ?",
            (chat_id, limit),
        ).fetchall()
    finally:
        c.close()
    return [{"author": a, "text": t} for a, t in reversed(rows)]


def recent_bot_replies(chat_id: int, limit: int = 5) -> list:
    c = _conn()
    try:
        rows = c.execute(
            "SELECT text FROM messages WHERE chat_id=? AND author='bot' "
            "ORDER BY id DESC LIMIT ?",
            (chat_id, limit),
        ).fetchall()
    finally:
        c.close()
    return [t for (t,) in rows]


def record_line(chat_id: int, line_id: str) -> None:
    c = _conn()
    try:
        c.execute("INSERT INTO used_lines (chat_id, line_id, ts) VALUES (?,?,?)",
                  (chat_id, line_id, time.time()))
        c.execute(
            "DELETE FROM used_lines WHERE chat_id=? AND rowid NOT IN "
            "(SELECT rowid FROM used_lines WHERE chat_id=? ORDER BY ts DESC LIMIT ?)",
            (chat_id, chat_id, _KEEP_LINE_WINDOW * 4),
        )
        c.commit()
    finally:
        c.close()


def recent_line_ids(chat_id: int, window: int = _KEEP_LINE_WINDOW) -> set:
    c = _conn()
    try:
        rows = c.execute(
            "SELECT line_id FROM used_lines WHERE chat_id=? ORDER BY ts DESC LIMIT ?",
            (chat_id, window),
        ).fetchall()
    finally:
        c.close()
    return {r[0] for r in rows}
