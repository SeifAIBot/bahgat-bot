import sqlite3
import time

import pytest

from brain import memory


@pytest.fixture()
def tmp_db(tmp_path, monkeypatch):
    db = tmp_path / "test.db"
    monkeypatch.setattr(memory, "DB_PATH", db)
    monkeypatch.setattr(memory, "_SCHEMA_DONE", False)
    memory.init_db()
    yield db
    monkeypatch.setattr(memory, "_SCHEMA_DONE", False)


def test_quota_fair_share_blocks_over_share(tmp_db):
    # v0.7: no fixed 100/user/day cap any more. Strict mode (group used
    # >= 50% of C): a member is held to their share. C=1500, 15 active
    # (owner + 14) -> member share ~98.36; 99 used -> denied.
    import sqlite3
    c = sqlite3.connect(tmp_db)
    c.execute("INSERT INTO daily_usage(user_id, chat_id, date, count) "
              "VALUES(888, 999, date('now'), 651)")
    c.execute("INSERT INTO daily_usage(user_id, chat_id, date, count) "
              "VALUES(111, 999, date('now'), 99)")
    c.commit()
    c.close()
    allowed, reason = memory.check_and_consume_quota(
        111, 999, owner_id=1415214630, capacity_replies=1500.0,
        active_users=[1415214630] + list(range(2, 16)))
    assert allowed is False
    assert reason == "fair share reached"
    # Denied calls do not increment.
    assert memory.get_usage_today()["per_user"][111] == 99


def test_quota_group_hard_ceiling(tmp_db):
    # The group pool itself is a hard ceiling: used_group >= C denies
    # everyone, even a user under the floor.
    import sqlite3
    c = sqlite3.connect(tmp_db)
    c.execute("INSERT INTO daily_usage(user_id, chat_id, date, count) "
              "VALUES(888, 555, date('now'), 100)")
    c.commit()
    c.close()
    allowed, reason = memory.check_and_consume_quota(
        2000, 555, capacity_replies=100.0, active_users=[2000])
    assert allowed is False
    assert "group" in reason


def test_get_usage_today(tmp_db):
    memory.check_and_consume_quota(1, 10, capacity_replies=1500.0)
    memory.check_and_consume_quota(1, 10, capacity_replies=1500.0)
    memory.check_and_consume_quota(2, 10, capacity_replies=1500.0)
    memory.check_and_consume_quota(1, 20, capacity_replies=1500.0)
    usage = memory.get_usage_today()
    assert usage["per_user"] == {1: 3, 2: 1}
    assert usage["by_chat"] == {10: 3, 20: 1}
    assert usage["group_total"] == 4
    # v0.7: the fixed group_limit/user_limit keys are gone with the
    # fixed caps — capacity is live now.
    assert "group_limit" not in usage
    assert "user_limit" not in usage


def test_recent_messages_speaker_tagged(tmp_db):
    memory.save_member({"user_id": 7, "username": "mo", "first_name": "محمد",
                        "notes": "", "mood": 30, "grudge": ""})
    memory.add_message(42, 7, "user", "عامل ايه يا بهجت")
    memory.add_message(42, 0, "assistant", "تمام يا عم")
    rows = memory.recent_messages(42, limit=8)
    assert rows[0]["role"] == "user"
    assert rows[0]["content"] == "عامل ايه يا بهجت"
    assert rows[0]["user_id"] == 7
    assert rows[0]["first_name"] == "محمد"
    hist = memory.format_history(rows)
    assert hist[0] == {"role": "user", "content": "[محمد]: عامل ايه يا بهجت"}
    assert hist[1] == {"role": "assistant", "content": "تمام يا عم"}


def test_mood_decay_persisted(tmp_db):
    memory.save_member({"user_id": 9, "username": "", "first_name": "سيف",
                        "notes": "", "mood": 80, "grudge": ""})
    # Fake "3 hours ago" — save_member always stamps now, so update directly.
    c = sqlite3.connect(tmp_db)
    c.execute("UPDATE members SET updated_at=? WHERE user_id=?",
              (time.time() - 3 * 3600, 9))
    c.commit()
    c.close()
    m1 = memory.get_member(9)
    assert m1["mood"] == 50  # 80 - 3*10
    m2 = memory.get_member(9)
    assert m2["mood"] == 50  # persisted: second read does NOT decay again to 20


def test_state_round_trip(tmp_db):
    assert memory.get_state("muted") is None
    memory.set_state("muted", "1")
    assert memory.get_state("muted") == "1"
    memory.set_state("muted", "0")
    assert memory.get_state("muted") == "0"


def test_youtube_file_cache_round_trip(tmp_db):
    assert memory.get_cached_file("vid123", False) is None
    memory.cache_file("vid123", False, "file_abc", 12345)
    assert memory.get_cached_file("vid123", False) == "file_abc"
    assert memory.get_cached_file("vid123", True) is None
    memory.cache_file("vid123", True, "file_audio", 999)
    assert memory.get_cached_file("vid123", True) == "file_audio"


def test_prune_processed_updates(tmp_db):
    c = sqlite3.connect(tmp_db)
    c.execute("INSERT INTO processed_updates(update_id, chat_id, received_at) VALUES(1, 1, ?)",
              (time.time() - 100 * 3600,))
    c.execute("INSERT INTO processed_updates(update_id, chat_id, received_at) VALUES(2, 1, ?)",
              (time.time(),))
    c.commit()
    c.close()
    deleted = memory.prune_processed_updates(hours=48)
    assert deleted == 1
    c = sqlite3.connect(tmp_db)
    remaining = c.execute("SELECT update_id FROM processed_updates").fetchall()
    c.close()
    assert remaining == [(2,)]
