"""SQLite state: recent messages, bot replies, served-line window."""
from bahgat import db


def test_messages_roundtrip(tmp_data):
    db.add_message(1, "كريم", "اهلا")
    db.add_message(1, "bot", "اهلا بيك")
    db.add_message(1, "كريم", "عامل ايه")
    rows = db.recent_messages(1)
    assert [r["author"] for r in rows] == ["كريم", "bot", "كريم"]
    assert rows[0]["text"] == "اهلا"


def test_messages_scoped_per_chat(tmp_data):
    db.add_message(1, "a", "chat one")
    db.add_message(2, "a", "chat two")
    assert [r["text"] for r in db.recent_messages(1)] == ["chat one"]
    assert [r["text"] for r in db.recent_messages(2)] == ["chat two"]


def test_recent_bot_replies(tmp_data):
    db.add_message(1, "كريم", "سؤال")
    db.add_message(1, "bot", "جواب ١")
    db.add_message(1, "bot", "جواب ٢")
    assert db.recent_bot_replies(1) == ["جواب ٢", "جواب ١"]


def test_message_cap(tmp_data):
    for i in range(60):
        db.add_message(1, "a", f"msg {i}")
    assert len(db.recent_messages(1, limit=100)) == 50


def test_used_lines_window(tmp_data):
    db.record_line(1, "in-01")
    db.record_line(1, "in-02")
    db.record_line(2, "in-09")
    assert db.recent_line_ids(1) == {"in-01", "in-02"}
    assert db.recent_line_ids(2) == {"in-09"}


# The v1.x messages table (memory/schema.sql at the v1.18 tag): same
# bahgat.db filename on the persistent volume, different columns.
OLD_MESSAGES_SCHEMA = """
CREATE TABLE messages (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  chat_id INTEGER,
  user_id INTEGER,
  role TEXT,
  text TEXT,
  created_at REAL
);
"""


def test_migrates_v1_messages_table(monkeypatch, tmp_path):
    """Live 2026-11-28: v2.2 went totally silent because the volume still
    held the v1.x bahgat.db — init_db's CREATE TABLE IF NOT EXISTS kept
    the old messages table, so every add_message raised OperationalError
    ("no column named author") before the bot could answer anything."""
    import sqlite3

    d = tmp_path / "data"
    d.mkdir()
    monkeypatch.setenv("BAHGAT_DATA_DIR", str(d))
    old = sqlite3.connect(d / "bahgat.db")
    old.executescript(OLD_MESSAGES_SCHEMA)
    old.execute(
        "INSERT INTO messages (chat_id, user_id, role, text, created_at) "
        "VALUES (?,?,?,?,?)", (1, 42, "user", "سؤال قديم", 1000.0))
    old.execute(
        "INSERT INTO messages (chat_id, user_id, role, text, created_at) "
        "VALUES (?,?,?,?,?)", (1, 0, "bot", "جواب قديم", 1001.0))
    old.commit()
    old.close()

    db.init_db()  # must migrate, not crash
    db.add_message(1, "كريم", "سؤال جديد")
    rows = db.recent_messages(1)
    assert [r["author"] for r in rows] == ["user", "bot", "كريم"]
    assert [r["text"] for r in rows] == ["سؤال قديم", "جواب قديم", "سؤال جديد"]
    assert db.recent_bot_replies(1) == ["جواب قديم"]
    db.init_db()  # second run is a no-op
    assert len(db.recent_messages(1)) == 3
