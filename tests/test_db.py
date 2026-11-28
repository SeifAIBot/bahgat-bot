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
