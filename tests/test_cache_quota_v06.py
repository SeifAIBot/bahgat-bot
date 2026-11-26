"""v0.6 cache + v0.7 fair-share quota tests — response cache (TTL,
buckets, exclusions), fair-share quota (live capacity, owner weight
1.25 instead of the v0.6 owner exemption, floor 20, borrow ceiling 2x),
unknown-retry counters, and the handler wiring (cache before quota,
group-quota reply, unknown gating, history limit 6).
"""
import sqlite3
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import tg.handlers as h
from brain import memory
from brain.memory import normalize_cache_text
from core.config import Settings

OWNER_ID = 1415214630


# --- memory-level: cache ----------------------------------------------------

def test_cache_hit_miss_and_stats(tmp_db):
    assert memory.get_cached_reply("ازيك يا بهجت", "just_chat", "calm") is None
    stats = memory.get_cache_stats()
    assert stats["misses"] == 1 and stats["hits"] == 0
    assert stats["hit_rate"] == 0.0
    memory.store_cached_reply("ازيك يا بهجت", "just_chat", "calm", "تمام يا عم")
    assert memory.get_cached_reply("ازيك يا بهجت", "just_chat", "calm") == "تمام يا عم"
    stats = memory.get_cache_stats()
    assert stats["hits"] == 1 and stats["misses"] == 1
    assert stats["hit_rate"] == 0.5


def test_cache_normalisation_collapses_arabic_variants(tmp_db):
    memory.store_cached_reply("اهلا يا بهجت", "just_chat", "calm", "اهلين يا عم")
    # Diacritics + hamza variants of the same text must hit the same entry.
    assert memory.get_cached_reply("أهلاً يا بهجت", "just_chat", "calm") == "اهلين يا عم"
    assert normalize_cache_text("أهلاً  يا  بهجت") == normalize_cache_text("اهلا يا بهجت")
    assert normalize_cache_text("Hello  WORLD") == "hello world"


def test_cache_ttl_expiry(tmp_db):
    memory.store_cached_reply("ازيك", "just_chat", "calm", "تمام يا عم")
    c = sqlite3.connect(tmp_db)
    c.execute("UPDATE response_cache SET created_at=?",
              (time.time() - 3700,))  # older than the 1h TTL
    c.commit()
    c.close()
    assert memory.get_cached_reply("ازيك", "just_chat", "calm") is None
    # Expired rows are deleted on read.
    c = sqlite3.connect(tmp_db)
    rows = c.execute("SELECT COUNT(*) FROM response_cache").fetchone()[0]
    c.close()
    assert rows == 0


def test_cache_mood_bucket_separation(tmp_db):
    memory.store_cached_reply("ازيك", "just_chat", "calm", "تمام يا عم، زي الفل")
    memory.store_cached_reply("ازيك", "just_chat", "angry", "انت عايز ايه دلوقتي")
    assert memory.get_cached_reply("ازيك", "just_chat", "calm") == "تمام يا عم، زي الفل"
    assert memory.get_cached_reply("ازيك", "just_chat", "angry") == "انت عايز ايه دلوقتي"
    assert memory.mood_bucket(69) == "calm"
    assert memory.mood_bucket(70) == "angry"
    assert memory.mood_bucket(30) == "calm"


def test_cache_store_skips_empty_and_caps_reply(tmp_db):
    memory.store_cached_reply("ازيك", "just_chat", "calm", "   ")
    assert memory.get_cached_reply("ازيك", "just_chat", "calm") is None
    memory.store_cached_reply("ازيك", "just_chat", "calm", "x" * 1500)
    assert len(memory.get_cached_reply("ازيك", "just_chat", "calm")) == 1000


def test_cache_prunes_to_last_500_rows(tmp_db):
    for i in range(505):
        memory.store_cached_reply(f"سؤال {i}", "just_chat", "calm", f"رد {i}")
    c = sqlite3.connect(tmp_db)
    rows = c.execute("SELECT COUNT(*) FROM response_cache").fetchone()[0]
    c.close()
    assert rows == 500
    # The newest rows survive; the oldest are gone.
    assert memory.get_cached_reply("سؤال 504", "just_chat", "calm") == "رد 504"
    assert memory.get_cached_reply("سؤال 0", "just_chat", "calm") is None


# --- memory-level: quota ----------------------------------------------------

def test_quota_fair_share_blocks_over_share(tmp_db):
    # v0.7 replaces the fixed 100/user/day cap: strict mode (group used
    # >= 50% of C) holds a member to their share. C=1500, 15 active
    # (owner + 14) -> member share ~98.36; 99 used -> denied.
    c = sqlite3.connect(tmp_db)
    c.execute("INSERT INTO daily_usage(user_id, chat_id, date, count) "
              "VALUES(888, 999, date('now'), 651)")
    c.execute("INSERT INTO daily_usage(user_id, chat_id, date, count) "
              "VALUES(111, 999, date('now'), 99)")
    c.commit()
    c.close()
    allowed, reason = memory.check_and_consume_quota(
        111, 999, owner_id=OWNER_ID, capacity_replies=1500.0,
        active_users=[OWNER_ID] + list(range(2, 16)))
    assert allowed is False
    assert reason == "fair share reached"
    assert memory.get_usage_today()["per_user"][111] == 99


def test_quota_no_hourly_cap_25_in_one_hour_allowed(tmp_db):
    # v0.6b: the 20/hour burst cap was removed at Seif's request — anti-spam
    # is now the 10s per-user reply pacing in tg/handlers.py. 25 calls in
    # the same hour must all be allowed (generous capacity, one active user).
    for _ in range(25):
        allowed, _ = memory.check_and_consume_quota(
            222, 999, capacity_replies=1500.0, active_users=[222])
        assert allowed is True


def test_quota_group_hard_ceiling_blocks(tmp_db):
    # v0.7: the group pool is a hard ceiling at the LIVE capacity C
    # (no fixed 1500 any more). used_group >= C denies everyone.
    c = sqlite3.connect(tmp_db)
    c.execute("INSERT INTO daily_usage(user_id, chat_id, date, count) "
              "VALUES(1, 555, date('now'), 100)")
    c.commit()
    c.close()
    allowed, reason = memory.check_and_consume_quota(
        9999, 555, capacity_replies=100.0, active_users=[9999])
    assert allowed is False
    assert reason == "group daily limit reached"
    # A different chat is unaffected.
    assert memory.check_and_consume_quota(
        9999, 556, capacity_replies=100.0, active_users=[9999])[0] is True


def test_quota_owner_not_exempt_but_weighted(tmp_db):
    # v0.7: the v0.6 owner exemption is REMOVED — the owner gets a 1.25
    # weight instead. Strict mode (group 750/1500), owner share ~122.95:
    # 123 used -> denied, and the denials still count what he used.
    c = sqlite3.connect(tmp_db)
    c.execute("INSERT INTO daily_usage(user_id, chat_id, date, count) "
              "VALUES(888, 999, date('now'), 627)")
    c.execute("INSERT INTO daily_usage(user_id, chat_id, date, count) "
              "VALUES(?, 999, date('now'), 123)", (OWNER_ID,))
    c.commit()
    c.close()
    allowed, reason = memory.check_and_consume_quota(
        OWNER_ID, 999, owner_id=OWNER_ID, capacity_replies=1500.0,
        active_users=[OWNER_ID] + list(range(2, 16)))
    assert allowed is False
    assert reason == "fair share reached"
    assert memory.get_usage_today()["per_user"][OWNER_ID] == 123


def test_group_pool_remaining_retired(tmp_db):
    # v0.7: group_pool_remaining() is deleted with the fixed caps; the
    # handler workstream replaces it with a capacity-based fraction
    # (pool_remaining / full_pool from compute_pool_remaining) driving
    # update_degrade_mode(). The capacity side is covered here.
    assert not hasattr(memory, "group_pool_remaining")
    res = memory.compute_pool_remaining(
        [{"name": "groq-20b", "family": "groq", "model": "m",
          "daily_cap_requests": 100, "daily_cap_tokens": None,
          "requests_used": 50, "tokens_used": 0, "disabled": False,
          "exhausted_until": None}], avg_tokens=1050)
    assert res["pool_replies"] == pytest.approx(40.0)   # (100-50) x 0.8
    assert res["full_pool_replies"] == pytest.approx(80.0)
    assert memory.update_degrade_mode(
        res["pool_replies"] / res["full_pool_replies"]) == "normal"


def test_hourly_usage_pruned_after_two_days(tmp_db):
    c = sqlite3.connect(tmp_db)
    old_hour = time.strftime("%Y-%m-%dT%H", time.gmtime(time.time() - 3 * 86400))
    c.execute("INSERT INTO hourly_usage(user_id, chat_id, hour, count) "
              "VALUES(1, 1, ?, 99)", (old_hour,))
    c.commit()
    c.close()
    memory.check_and_consume_quota(2, 1)
    c = sqlite3.connect(tmp_db)
    rows = c.execute("SELECT COUNT(*) FROM hourly_usage WHERE hour=?", (old_hour,)).fetchone()[0]
    c.close()
    assert rows == 0


def test_unknown_stats_counters(tmp_db):
    assert memory.get_unknown_stats() == {
        "unknown_retries": 0, "unknown_retries_rescued": 0, "unknown_retry_rate": 0.0}
    memory.record_unknown_retry(rescued=True)
    memory.record_unknown_retry(rescued=False)
    stats = memory.get_unknown_stats()
    assert stats["unknown_retries"] == 2
    assert stats["unknown_retries_rescued"] == 1
    assert stats["unknown_retry_rate"] == 0.5


# --- handler-level wiring ---------------------------------------------------

class FakeUser:
    def __init__(self, uid, first_name="Test", username="testuser", is_bot=False):
        self.id = uid
        self.first_name = first_name
        self.username = username
        self.is_bot = is_bot


class FakeChat:
    def __init__(self, chat_id):
        self.id = chat_id
        self.send_message = AsyncMock()


class FakeMessage:
    def __init__(self, text, chat_id, user, message_id=1, reply_to=None):
        self.text = text
        self.chat_id = chat_id
        self.message_id = message_id
        self.from_user = user
        self.reply_to_message = reply_to
        self.chat = FakeChat(chat_id)
        self.reply_text = AsyncMock(return_value=self)
        self.reply_voice = AsyncMock()
        self.reply_audio = AsyncMock()
        self.reply_video = AsyncMock()


class FakeBot:
    def __init__(self):
        self.username = "Bahgoti_bot"
        self.id = 9106462211
        self.send_chat_action = AsyncMock()
        self.get_chat_member = AsyncMock()


class FakeRouter:
    def __init__(self, replies=("تمام يا عم",)):
        self.replies = list(replies)
        self.calls = []

    async def chat(self, messages, hard=False, temperature=None, max_tokens=None):
        self.calls.append(messages)
        reply = self.replies.pop(0) if len(self.replies) > 1 else self.replies[0]
        return (reply, "groq", 10)


def make_ctx(bot, bot_data):
    app = SimpleNamespace(bot_data=bot_data)
    return SimpleNamespace(bot=bot, application=app)


def make_update(msg, user, chat_id, update_id=100):
    return SimpleNamespace(
        update_id=update_id, effective_message=msg, effective_user=user,
        effective_chat=FakeChat(chat_id), my_chat_member=None, callback_query=None,
    )


@pytest.fixture(autouse=True)
def reset_handler_state():
    for d in (h._last_reply_time, h._last_cooldown_notice, h._last_send, h._send_count,
              h._seen_callbacks, h._membership_cache, h._chat_locks,
              h._last_voice, h._last_anon_notice):
        d.clear()
    yield
    for d in (h._last_reply_time, h._last_cooldown_notice, h._last_send, h._send_count,
              h._seen_callbacks, h._membership_cache, h._chat_locks,
              h._last_voice, h._last_anon_notice):
        d.clear()


@pytest.fixture
def handler_env(monkeypatch):
    """Real quota/cache (tmp DB via conftest tmp_db); member/history faked."""
    def _get_member(uid):
        return {"user_id": uid, "username": "", "first_name": "Test",
                "notes": "", "mood": 30, "grudge": "", "updated_at": time.time()}

    monkeypatch.setattr(h, "get_member", _get_member)
    monkeypatch.setattr(h, "save_member", lambda m: None)
    monkeypatch.setattr(h, "add_message", lambda *a, **k: None)
    monkeypatch.setattr(h, "recent_messages", lambda chat_id, limit=8: [])
    monkeypatch.setattr("random.random", lambda: 0.99)  # no random voice


@pytest.fixture
def settings():
    return Settings(telegram_bot_token="x", owner_id=OWNER_ID, allowed_chat_ids="")


def _ctx(settings, router):
    bot = FakeBot()
    return make_ctx(bot, {"settings": settings, "router": router, "yt_requests": {}})


def _sent_texts(msg):
    return [c.args[0] for c in msg.reply_text.call_args_list]


async def test_handler_cache_hit_skips_router_and_quota(
        handler_env, settings, tmp_db):
    router = FakeRouter()
    ctx = _ctx(settings, router)
    user = FakeUser(777, first_name="Ahmed")
    msg = FakeMessage("بهجت ازيك؟", -100222, user)
    await h._on_group_message_inner(make_update(msg, user, -100222, update_id=301), ctx)
    assert len(router.calls) == 1
    assert memory.get_usage_today()["per_user"][777] == 1

    # Same text again: cache hit — no router call, no quota consumed.
    h._last_reply_time.clear()
    h._last_cooldown_notice.clear()
    msg2 = FakeMessage("بهجت ازيك؟", -100222, user)
    await h._on_group_message_inner(make_update(msg2, user, -100222, update_id=302), ctx)
    assert len(router.calls) == 1
    assert memory.get_usage_today()["per_user"][777] == 1
    assert "تمام يا عم" in _sent_texts(msg2)
    assert memory.get_cache_stats()["hits"] >= 1


async def test_handler_search_intent_never_cached(
        handler_env, settings, tmp_db, monkeypatch):
    async def _fake_grounding(query):
        return "[SEARCH FAILED] — مفيش نتائج موثوقة، متخترعش."

    monkeypatch.setattr(h, "_search_grounding", _fake_grounding)
    router = FakeRouter()
    ctx = _ctx(settings, router)
    user = FakeUser(777, first_name="Ahmed")
    msg = FakeMessage("بهجت كام سعر الدولار", -100222, user)
    await h._on_group_message_inner(make_update(msg, user, -100222, update_id=311), ctx)
    assert len(router.calls) == 1
    assert memory.get_cached_reply(
        normalize_cache_text("بهجت كام سعر الدولار"), "search", "calm") is None


async def test_handler_insult_never_cached(handler_env, settings, tmp_db):
    router = FakeRouter()
    ctx = _ctx(settings, router)
    user = FakeUser(777, first_name="Ahmed")
    msg = FakeMessage("بهجت انت حمار", -100222, user)
    await h._on_group_message_inner(make_update(msg, user, -100222, update_id=321), ctx)
    assert len(router.calls) == 1
    assert memory.get_cached_reply(
        normalize_cache_text("بهجت انت حمار"), "just_chat", "angry") is None


async def test_handler_group_quota_reply_differs(handler_env, settings, tmp_db, monkeypatch):
    user = FakeUser(777, first_name="Ahmed")
    # v0.7: the memory quota stub takes the new signature (owner_id,
    # capacity_replies, active_users, quota_cfg) and returns the new
    # reasons ("group daily limit reached" / "fair share reached").
    monkeypatch.setattr(
        "brain.memory.check_and_consume_quota",
        lambda u, c, owner_id=None, capacity_replies=None, active_users=None,
        quota_cfg=None: (False, "group daily limit reached"), raising=False)
    router = FakeRouter()
    ctx = _ctx(settings, router)
    # v1.0: greetings ("بهجت ازيك يا عم", "بهجت عامل ايه") take the fast
    # path now and never reach the quota check — a real question is the
    # right probe for a quota reply.
    msg = FakeMessage("بهجت ايه رايك في مروان موسي", -100222, user)
    await h._on_group_message_inner(make_update(msg, user, -100222, update_id=331), ctx)
    assert len(router.calls) == 0
    assert any("الجروب خلص حصته" in t for t in _sent_texts(msg))

    monkeypatch.setattr(
        "brain.memory.check_and_consume_quota",
        lambda u, c, owner_id=None, capacity_replies=None, active_users=None,
        quota_cfg=None: (False, "fair share reached"), raising=False)
    h._last_reply_time.clear()
    msg2 = FakeMessage("بهجت ايه رايك في الكورة", -100222, user)
    await h._on_group_message_inner(make_update(msg2, user, -100222, update_id=332), ctx)
    assert any("كفاية كده النهاردة" in t for t in _sent_texts(msg2))


async def test_handler_low_pool_notice_once_per_hour(
        handler_env, settings, tmp_db, monkeypatch):
    # v0.7 hysteresis: the notice fires only on the TRANSITION into
    # cheap mode (memory.update_degrade_mode), not on a fixed 20%
    # threshold — the old daily_usage drain no longer drives it.
    monkeypatch.setattr(
        "brain.memory.update_degrade_mode", lambda fraction: "cheap", raising=False)
    router = FakeRouter()
    ctx = _ctx(settings, router)
    user = FakeUser(777, first_name="Ahmed")
    msg = FakeMessage("بهجت ازيك؟", -100222, user)
    await h._on_group_message_inner(make_update(msg, user, -100222, update_id=341), ctx)
    assert len(router.calls) == 1  # still served, not blocked
    assert any("البطارية" in t for t in _sent_texts(msg))

    # Second turn within the hour: served, but no second notice — the
    # mode was already cheap, so there is no new transition.
    h._last_reply_time.clear()
    h._last_cooldown_notice.clear()
    msg2 = FakeMessage("بهجت ايه رايك في الكورة", -100222, user)
    await h._on_group_message_inner(make_update(msg2, user, -100222, update_id=342), ctx)
    assert len(router.calls) == 2
    assert not any("البطارية" in t for t in _sent_texts(msg2))


async def test_handler_history_limit_is_six(handler_env, settings, tmp_db, monkeypatch):
    seen_limits = []

    def _recording_recent(chat_id, limit=8):
        seen_limits.append(limit)
        return []

    monkeypatch.setattr(h, "recent_messages", _recording_recent)
    router = FakeRouter()
    ctx = _ctx(settings, router)
    user = FakeUser(777, first_name="Ahmed")
    msg = FakeMessage("بهجت ازيك؟", -100222, user)
    await h._on_group_message_inner(make_update(msg, user, -100222, update_id=351), ctx)
    assert 6 in seen_limits  # LLM turn uses 6 (was 8); speakers lookup uses 20


async def test_handler_unknown_retry_rescues_when_no_search_ran(
        handler_env, settings, tmp_db, monkeypatch):
    async def _fake_grounding(query):
        return ("[1] http://example.com — " + "نص طويل من صفحة موثوقة. " * 20)

    monkeypatch.setattr(h, "_search_grounding", _fake_grounding)
    router = FakeRouter(replies=("مش عارف", "الأهلي كسب 2-1"))
    ctx = _ctx(settings, router)
    user = FakeUser(777, first_name="Ahmed")
    msg = FakeMessage("بهجت ازيك؟", -100222, user)
    await h._on_group_message_inner(make_update(msg, user, -100222, update_id=361), ctx)
    assert len(router.calls) == 2  # first unknown -> search + retry
    assert any("الأهلي كسب" in t for t in _sent_texts(msg))
    assert memory.get_unknown_stats()["unknown_retries_rescued"] == 1


async def test_handler_search_already_ran_retries_once_from_grounding(
        handler_env, settings, tmp_db, monkeypatch):
    # v0.9: when a search already ran and the first reply is still
    # unknown, the turn retries ONCE with a firm instruction instead of
    # sending the old "مش جوجل، بس هدورلك" deflection (a promise of a
    # search that no later turn delivers).
    async def _fake_grounding(query):
        return ("[1] http://example.com — " + "نص طويل من صفحة موثوقة. " * 20)

    monkeypatch.setattr(h, "_search_grounding", _fake_grounding)
    router = FakeRouter(replies=("مش عارف", "الأهلي كسب 2-1"))
    ctx = _ctx(settings, router)
    user = FakeUser(777, first_name="Ahmed")
    msg = FakeMessage("بهجت كام سعر الدولار", -100222, user)
    await h._on_group_message_inner(make_update(msg, user, -100222, update_id=371), ctx)
    assert len(router.calls) == 2  # firm retry from the grounding
    assert any("الأهلي كسب" in t for t in _sent_texts(msg))
    assert not any("هدورلك" in t for t in _sent_texts(msg))
    assert memory.get_unknown_stats()["unknown_retries_rescued"] == 1


async def test_stats_shows_cache_and_pool(handler_env, settings, tmp_db, monkeypatch):
    monkeypatch.setattr(
        "brain.memory.get_usage_today",
        lambda: {"per_user": {777: 5}, "group_total": 5, "by_chat": {-100222: 5},
                 "group_limit": 1500, "user_limit": 100}, raising=False)
    # v0.7: /stats reads live data from the router's pool snapshot and
    # the memory fair-share / EWMA / degrade APIs (mocked here).
    monkeypatch.setattr(
        "brain.memory.fair_share_info",
        lambda u, c, owner_id=None, capacity_replies=None, active_users=None,
        quota_cfg=None: {"share": 100.0, "ceiling": 200.0, "limit": 100.0,
                         "used_user": 5, "used_group": 5, "capacity": 1200.0,
                         "active_count": 2, "saturated": False}, raising=False)
    monkeypatch.setattr(
        "brain.memory.avg_tokens_per_reply",
        lambda intent=None: 1050.0 if intent == "chat" else 2400.0, raising=False)
    monkeypatch.setattr(
        "brain.memory.active_users", lambda chat_id, window_days=7: [777, 888],
        raising=False)
    monkeypatch.setattr(
        "brain.memory.get_degrade_mode", lambda: ("normal", None, False),
        raising=False)

    class StatsRouter:
        def pool_remaining_replies(self):
            return {"pool_replies": 1200.0, "full_pool_replies": 1500.0,
                    "avg_tokens": 1050.0,
                    "per_entry": [
                        {"name": "groq-20b", "family": "groq",
                         "model": "openai/gpt-oss-20b",
                         "daily_cap_requests": 1000, "daily_cap_tokens": 180000,
                         "requests_used": 10, "tokens_used": 10500,
                         "disabled": False, "exhausted_until": None},
                        {"name": "gemini-gemma", "family": "gemini",
                         "model": "gemma-4-31b-it",
                         "daily_cap_requests": 14400, "daily_cap_tokens": None,
                         "requests_used": 100, "tokens_used": 0,
                         "disabled": False, "exhausted_until": None},
                    ]}

    memory.store_cached_reply("ازيك", "just_chat", "calm", "تمام يا عم")
    memory.get_cached_reply("ازيك", "just_chat", "calm")
    user = FakeUser(OWNER_ID, first_name="سيف")
    msg = FakeMessage("/stats", -100222, user)
    ctx = make_ctx(FakeBot(), {"settings": settings, "router": StatsRouter()})
    await h.on_stats(make_update(msg, user, -100222), ctx)
    assert msg.reply_text.called
    text = msg.reply_text.call_args.args[0]
    assert "1200" in text  # pool remaining in replies
    assert "حصة الجروب" in text
    assert "الوضع: عادي" in text
    assert "المستخدمين النشطين: 2" in text
    assert "1050" in text and "2400" in text  # avg tokens chat + search
    assert "Test: 5/100" in text  # per-user fair share used/limit
    assert "groq-20b" in text and "gemini-gemma" in text  # per-provider
    assert "الكاش" in text
    assert len(text.splitlines()) <= 20
