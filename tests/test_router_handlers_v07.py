"""v0.7 router + handler integration tests — Gemini Pacific-date keying,
pool_snapshot / pool_remaining_replies, cheap-only routing, EWMA
recording, trigger recording, quota forwarding (capacity + active users),
hysteresis degrade wiring, and the rewritten /stats.

brain.memory's v0.7 functions are owned by a parallel workstream, so
every memory function used here is monkeypatched onto brain.memory in
the test (raising=False); handlers/routers look them up dynamically.
"""
import asyncio
import calendar
import sqlite3
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import tg.handlers as h
from brain.router import BrainRouter
from core.config import Settings

OWNER_ID = 1415214630
# 2026-11-26 07:30 UTC = 2026-11-25 23:30 Pacific: the two dates differ.
TS_SPLIT = calendar.timegm((2026, 11, 26, 7, 30, 0, 0, 0, 0))
TS_SAME = calendar.timegm((2026, 11, 26, 9, 0, 0, 0, 0, 0))  # 01:00 Pacific

CHEAP = {"groq-20b", "cerebras-120b", "gemini-3.5-flash-lite",
         "gemini-3.1-flash-lite", "gemini-gemma"}


def _all_keys():
    return SimpleNamespace(
        gemini_api_key="fake-gemini", groq_api_key="fake-groq",
        cerebras_api_key="fake-cerebras", nvidia_api_key="fake-nvidia",
        openrouter_api_key="fake-openrouter")


def _router(tmp_path, settings=None):
    router = BrainRouter(settings or _all_keys())
    router.db = tmp_path / "router.db"
    return router


def _seed(router, provider, model, requests=0, tokens_in=0, tokens_out=0, date=None):
    router.db.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(router.db)
    router._ensure_usage_table(c)
    c.execute("INSERT INTO provider_usage(provider, model, date, requests, tokens_in, tokens_out)"
              " VALUES(?,?,?,?,?,?)",
              (provider, model, date or time.strftime("%Y-%m-%d", time.gmtime()),
               requests, tokens_in, tokens_out))
    c.commit()
    c.close()


class _FakeCompletions:
    def __init__(self, calls, fail_models=None, fail_status=503):
        self._calls = calls
        self._fail_models = set(fail_models or [])
        self._fail_status = fail_status

    async def create(self, **kwargs):
        self._calls.append(kwargs)
        if kwargs.get("model") in self._fail_models:
            class E(Exception):
                status_code = self._fail_status

            raise E("boom")
        usage = SimpleNamespace(prompt_tokens=10, completion_tokens=5,
                                completion_tokens_details=None,
                                prompt_tokens_details=None)
        msg = SimpleNamespace(content="اهلا يا عم")
        choice = SimpleNamespace(message=msg, finish_reason="stop")
        return SimpleNamespace(choices=[choice], usage=usage)


class _FakeClient:
    def __init__(self, calls, **kw):
        self.chat = SimpleNamespace(completions=_FakeCompletions(calls, **kw))

    async def close(self):
        pass


# --- 1. Gemini Pacific-date keying -------------------------------------------

def test_date_for_gemini_is_pacific_not_utc():
    # 07:30 UTC on 2026-11-26 is still 2026-11-25 in Pacific (UTC-8).
    assert BrainRouter._date_for("gemini", now=TS_SPLIT) == "2026-11-25"
    assert BrainRouter._date_for("groq", now=TS_SPLIT) == "2026-11-26"
    assert BrainRouter._date_for("cerebras", now=TS_SPLIT) == "2026-11-26"
    # 09:00 UTC is 01:00 Pacific the same calendar day.
    assert BrainRouter._date_for("gemini", now=TS_SAME) == "2026-11-26"
    assert BrainRouter._date_for("groq", now=TS_SAME) == "2026-11-26"


def test_gemini_usage_written_and_read_under_pacific_date(tmp_path, monkeypatch):
    router = _router(tmp_path)
    monkeypatch.setattr("brain.router.time.time", lambda: TS_SPLIT)
    router._record_usage("gemini-3.5-flash-lite", 100, 50,
                         model="gemini-3.5-flash-lite")
    router._record_usage("groq-20b", 7, 8, model="openai/gpt-oss-20b")
    c = sqlite3.connect(router.db)
    rows = {(p, d): (r, ti, to) for p, d, r, ti, to in c.execute(
        "SELECT provider, date, requests, tokens_in, tokens_out FROM provider_usage")}
    c.close()
    # Gemini row keyed by the Pacific date, Groq row by the UTC date.
    assert rows[("gemini-3.5-flash-lite", "2026-11-25")] == (1, 100, 50)
    assert rows[("groq-20b", "2026-11-26")] == (1, 7, 8)
    # Reads see the same split: Gemini usage is the Pacific row only.
    assert router._provider_usage_today("gemini-3.5-flash-lite") == (1, 100, 50)
    assert router._provider_usage_today("groq-20b") == (1, 7, 8)


def test_gemini_ban_keyed_by_pacific_date(tmp_path, monkeypatch):
    router = _router(tmp_path)
    monkeypatch.setattr("brain.router.time.time", lambda: TS_SPLIT)
    router._mark_exhausted("gemini-3.5-flash-lite", seconds=3600,
                           model="gemini-3.5-flash-lite")
    assert router._quota_exhausted("gemini-3.5-flash-lite")
    assert not router._quota_exhausted("groq-20b")
    # The ban row itself sits on the Pacific date.
    c = sqlite3.connect(router.db)
    dates = [r[0] for r in c.execute(
        "SELECT date FROM provider_usage WHERE provider='gemini-3.5-flash-lite'")]
    c.close()
    assert dates == ["2026-11-25"]


# --- 2. Capacity snapshot ------------------------------------------------------

def test_pool_snapshot_shape_and_usage(tmp_path):
    router = _router(tmp_path)
    _seed(router, "groq-20b", "openai/gpt-oss-20b", requests=2, tokens_in=4000,
          tokens_out=1000)
    snap = router.pool_snapshot()
    assert len(snap) == len(router.entries)
    by_name = {e["name"]: e for e in snap}
    assert set(by_name) == {e["name"] for e in router.entries}
    groq20 = by_name["groq-20b"]
    assert groq20 == {"name": "groq-20b", "family": "groq",
                      "model": "openai/gpt-oss-20b",
                      "daily_cap_requests": 1000, "daily_cap_tokens": 180000,
                      "requests_used": 2, "tokens_used": 5000,
                      "disabled": False, "exhausted_until": None}
    # Every entry carries the full key set.
    for e in snap:
        assert set(e) == {"name", "family", "model", "daily_cap_requests",
                          "daily_cap_tokens", "requests_used", "tokens_used",
                          "disabled", "exhausted_until"}


def test_pool_snapshot_disabled_and_banned(tmp_path):
    router = _router(tmp_path)
    router._disabled.add("cerebras-120b")
    router._mark_exhausted("groq-20b", seconds=3600, model="openai/gpt-oss-20b")
    by_name = {e["name"]: e for e in router.pool_snapshot()}
    assert by_name["cerebras-120b"]["disabled"] is True
    assert by_name["groq-20b"]["disabled"] is True
    assert by_name["groq-20b"]["exhausted_until"] is not None
    assert by_name["groq-20b"]["exhausted_until"] > time.time()
    assert by_name["gemini-gemma"]["disabled"] is False
    assert by_name["gemini-gemma"]["exhausted_until"] is None


def test_pool_remaining_replies_fail_closed_without_compute(tmp_path, monkeypatch):
    # Capacity must fail CLOSED at 0 when compute_pool_remaining is
    # unavailable (forced missing here) — never invent a pool.
    router = _router(tmp_path)
    monkeypatch.setattr("brain.memory.compute_pool_remaining", None, raising=False)
    monkeypatch.delattr("brain.memory.avg_tokens_per_reply", raising=False)
    result = router.pool_remaining_replies()
    assert result["pool_replies"] == 0.0
    assert result["full_pool_replies"] == 0.0
    assert result["avg_tokens"] == 1050.0  # fallback estimate, no EWMA fn
    assert len(result["per_entry"]) == len(router.entries)


def test_pool_remaining_replies_uses_compute_and_ewma_avg(tmp_path, monkeypatch):
    router = _router(tmp_path)
    seen = {}

    def _compute(entries, avg_tokens=None):
        seen["avg"] = avg_tokens
        return {"pool_replies": 42.5, "full_pool_replies": 100.0,
                "avg_tokens": avg_tokens, "per_entry": entries}

    monkeypatch.setattr(
        "brain.memory.compute_pool_remaining", _compute, raising=False)
    monkeypatch.setattr(
        "brain.memory.avg_tokens_per_reply", lambda intent=None: 1000.0,
        raising=False)
    result = router.pool_remaining_replies()
    assert result["pool_replies"] == 42.5
    assert result["full_pool_replies"] == 100.0
    assert result["avg_tokens"] == 1000.0
    assert seen["avg"] == 1000.0
    assert len(result["per_entry"]) == len(router.entries)


def test_pool_remaining_replies_avg_falls_back_to_1050(tmp_path, monkeypatch):
    router = _router(tmp_path)
    captured = {}

    def _compute(entries, avg_tokens=None):
        captured["avg"] = avg_tokens
        return {"pool_replies": 10.0, "full_pool_replies": 10.0,
                "avg_tokens": avg_tokens, "per_entry": entries}

    monkeypatch.setattr(
        "brain.memory.compute_pool_remaining", _compute, raising=False)
    # avg_tokens_per_reply missing -> 1050 fallback is passed through.
    monkeypatch.delattr("brain.memory.avg_tokens_per_reply", raising=False)
    result = router.pool_remaining_replies()
    assert result["pool_replies"] == 10.0
    assert captured["avg"] == 1050.0


# --- 3. Cheap-only routing + EWMA ----------------------------------------------

def test_cheap_only_plan_contains_only_cheap_entries(tmp_path):
    router = _router(tmp_path)
    simple_cheap = {e["name"] for e in router._build_plan(hard=False, cheap_only=True)}
    hard_cheap = {e["name"] for e in router._build_plan(hard=True, cheap_only=True)}
    assert simple_cheap <= CHEAP and simple_cheap
    assert hard_cheap <= CHEAP and hard_cheap
    assert "gemini-3-flash-preview" not in simple_cheap | hard_cheap
    assert "nvidia-nemotron" not in simple_cheap | hard_cheap
    # Simple cheap plan: groq-20b + cerebras + both flash-lites (gemma is
    # not in simple_order, so it is absent here, not by filtering).
    assert simple_cheap == {"groq-20b", "cerebras-120b",
                            "gemini-3.5-flash-lite", "gemini-3.1-flash-lite"}
    assert hard_cheap == {"cerebras-120b", "gemini-3.5-flash-lite",
                          "gemini-3.1-flash-lite", "gemini-gemma"}
    # Normal plans are unchanged: nvidia / flash-preview still present.
    assert "nvidia-nemotron" in {e["name"] for e in router._build_plan(hard=False)}
    assert "gemini-3-flash-preview" in {e["name"] for e in router._build_plan(hard=True)}


def test_chat_cheap_only_never_calls_flash_preview_or_nvidia(tmp_path):
    router = _router(tmp_path)
    calls = []
    # Every cheap model 503s; flash-preview + nvidia would succeed if tried.
    fail = {"openai/gpt-oss-20b", "gpt-oss-120b", "gemini-3.5-flash-lite",
            "gemini-3.1-flash-lite", "gemma-4-31b-it"}
    router._client = lambda name: _FakeClient(calls, fail_models=fail)
    text, provider, _ = asyncio.run(router.chat(
        [{"role": "user", "content": "hi"}], hard=True, cheap_only=True))
    assert provider == "none"  # no cheap entry left; no fallback to expensive
    tried = {c["model"] for c in calls}
    assert "gemini-3-flash-preview" not in tried
    assert "nvidia/nemotron-3.5-super-vl-120b-a12b" not in tried
    assert tried <= fail


def test_chat_records_reply_tokens_once_per_success(tmp_path, monkeypatch):
    router = _router(tmp_path)
    recorded = []
    monkeypatch.setattr(
        "brain.memory.record_reply_tokens",
        lambda intent, total: recorded.append((intent, total)), raising=False)
    calls = []
    router._client = lambda name: _FakeClient(calls)
    asyncio.run(router.chat([{"role": "user", "content": "hi"}],
                            hard=False, intent="chat"))
    assert recorded == [("chat", 15)]  # prompt 10 + completion 5, once
    recorded.clear()
    asyncio.run(router.chat([{"role": "user", "content": "مين كسب؟"}],
                            hard=True, intent="search"))
    assert recorded == [("search", 15)]


def test_chat_records_nothing_on_failure(tmp_path, monkeypatch):
    router = _router(tmp_path)
    recorded = []
    monkeypatch.setattr(
        "brain.memory.record_reply_tokens",
        lambda intent, total: recorded.append((intent, total)), raising=False)
    calls = []
    all_models = {e["model"] for e in router.entries}
    router._client = lambda name: _FakeClient(calls, fail_models=all_models)
    text, provider, _ = asyncio.run(router.chat(
        [{"role": "user", "content": "hi"}], hard=False, intent="chat"))
    assert provider == "none"
    assert recorded == []


def test_chat_works_when_ewma_function_missing(tmp_path, monkeypatch):
    # No record_reply_tokens in memory: the reply still succeeds.
    router = _router(tmp_path)
    monkeypatch.delattr("brain.memory.record_reply_tokens", raising=False)
    calls = []
    router._client = lambda name: _FakeClient(calls)
    text, provider, _ = asyncio.run(router.chat(
        [{"role": "user", "content": "hi"}], hard=False, intent="chat"))
    assert text == "اهلا يا عم" and provider == "groq"


# --- handlers ------------------------------------------------------------------

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


class FakeRouterV07:
    """Router stub with the v0.7 surface: chat(cheap_only, intent) +
    pool_remaining_replies()."""

    def __init__(self, reply="تمام يا عم", pool=None):
        self.reply = reply
        self.calls = []
        self.chat_kwargs = []
        self.pool_calls = 0
        self._pool = pool if pool is not None else {
            "pool_replies": 800.0, "full_pool_replies": 1000.0,
            "avg_tokens": 1050.0, "per_entry": []}

    async def chat(self, messages, hard=False, temperature=None, max_tokens=None,
                   cheap_only=False, intent=None):
        self.calls.append(messages)
        self.chat_kwargs.append({"cheap_only": cheap_only, "intent": intent,
                                 "hard": hard})
        return (self.reply, "groq", 10)

    def pool_remaining_replies(self):
        self.pool_calls += 1
        return dict(self._pool)


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


def test_check_quota_back_compat_old_two_arg_stub(monkeypatch):
    # An old (u, c) stub keeps working through the new _check_quota,
    # with or without the new kwargs.
    monkeypatch.setattr(
        "brain.memory.check_and_consume_quota",
        lambda u, c: (False, "fair share reached"), raising=False)
    assert h._check_quota(1, 2) == (False, "fair share reached")
    assert h._check_quota(1, 2, capacity_replies=800.0,
                          active_users=[1, 2]) == (False, "fair share reached")


async def test_trigger_recorded_on_triggered_turn(handler_env, settings, tmp_db, monkeypatch):
    recorded = []
    monkeypatch.setattr(
        "brain.memory.record_trigger",
        lambda user_id, chat_id: recorded.append((user_id, chat_id)), raising=False)
    router = FakeRouterV07()
    ctx = _ctx(settings, router)
    user = FakeUser(777, first_name="Ahmed")
    msg = FakeMessage("بهجت ازيك؟", -100222, user)
    await h._on_group_message_inner(make_update(msg, user, -100222, update_id=401), ctx)
    # The handler records the trigger; memory.check_and_consume_quota
    # also calls record_trigger itself (same upsert, idempotent), so the
    # count is >= 1 rather than exactly 1.
    assert (777, -100222) in recorded
    assert len(router.calls) == 1
    n_after_first = len(recorded)

    # Second turn, same text: a cache hit still records the trigger
    # (exactly one more — the cache path returns before quota, so only
    # the handler's call runs).
    h._last_reply_time.clear()
    msg2 = FakeMessage("بهجت ازيك؟", -100222, user)
    await h._on_group_message_inner(make_update(msg2, user, -100222, update_id=402), ctx)
    assert len(recorded) == n_after_first + 1
    assert len(router.calls) == 1  # cache hit: no second router call

    # A message that does NOT trigger the bot records nothing.
    h._last_reply_time.clear()
    msg3 = FakeMessage("ازيك يا عم", -100222, user)
    await h._on_group_message_inner(make_update(msg3, user, -100222, update_id=403), ctx)
    assert len(recorded) == n_after_first + 1


async def test_quota_receives_capacity_and_active_users_once(handler_env, settings, tmp_db, monkeypatch):
    seen = {}

    def _quota_stub(u, c, owner_id=None, capacity_replies=None, active_users=None,
                    quota_cfg=None):
        seen["kwargs"] = {"owner_id": owner_id, "capacity_replies": capacity_replies,
                          "active_users": active_users, "quota_cfg": quota_cfg}
        return (True, "ok")

    monkeypatch.setattr(
        "brain.memory.check_and_consume_quota", _quota_stub, raising=False)
    monkeypatch.setattr(
        "brain.memory.active_users", lambda chat_id, window_days=7: [777, 888],
        raising=False)
    router = FakeRouterV07()
    ctx = _ctx(settings, router)
    user = FakeUser(777, first_name="Ahmed")
    msg = FakeMessage("بهجت ازيك؟", -100222, user)
    await h._on_group_message_inner(make_update(msg, user, -100222, update_id=411), ctx)
    assert seen["kwargs"]["capacity_replies"] == 800.0
    assert seen["kwargs"]["active_users"] == [777, 888]
    assert seen["kwargs"]["owner_id"] == OWNER_ID
    assert router.pool_calls == 1  # capacity computed ONCE per turn
    assert len(router.calls) == 1


async def test_hysteresis_cheap_mode_passes_cheap_only(handler_env, settings, tmp_db, monkeypatch):
    monkeypatch.setattr(
        "brain.memory.update_degrade_mode", lambda fraction: "cheap", raising=False)
    router = FakeRouterV07(pool={"pool_replies": 100.0, "full_pool_replies": 1000.0,
                                 "avg_tokens": 1050.0, "per_entry": []})
    ctx = _ctx(settings, router)
    user = FakeUser(777, first_name="Ahmed")
    msg = FakeMessage("بهجت ازيك؟", -100222, user)
    await h._on_group_message_inner(make_update(msg, user, -100222, update_id=421), ctx)
    assert len(router.calls) == 1
    assert router.chat_kwargs[0]["cheap_only"] is True
    assert router.chat_kwargs[0]["intent"] == "just_chat"
    # Transition into cheap -> the low-pool notice is sent.
    assert any("البطارية" in t for t in _sent_texts(msg))


async def test_hysteresis_normal_mode_no_cheap_only_no_notice(handler_env, settings, tmp_db, monkeypatch):
    monkeypatch.setattr(
        "brain.memory.update_degrade_mode", lambda fraction: "normal", raising=False)
    router = FakeRouterV07()
    ctx = _ctx(settings, router)
    user = FakeUser(777, first_name="Ahmed")
    msg = FakeMessage("بهجت ازيك؟", -100222, user)
    await h._on_group_message_inner(make_update(msg, user, -100222, update_id=431), ctx)
    assert len(router.calls) == 1
    assert router.chat_kwargs[0]["cheap_only"] is False
    assert not any("البطارية" in t for t in _sent_texts(msg))


async def test_stats_shows_pool_fair_share_mode_and_providers(
        handler_env, settings, tmp_db, monkeypatch):
    monkeypatch.setattr(
        "brain.memory.get_usage_today",
        lambda: {"per_user": {777: 5}, "group_total": 5, "by_chat": {-100222: 5}},
        raising=False)
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
        "brain.memory.get_degrade_mode", lambda: ("cheap", 1234567890.0, True),
        raising=False)
    router = FakeRouterV07(pool={
        "pool_replies": 1200.0, "full_pool_replies": 1500.0, "avg_tokens": 1050.0,
        "per_entry": [
            {"name": "groq-20b", "family": "groq", "model": "openai/gpt-oss-20b",
             "daily_cap_requests": 1000, "daily_cap_tokens": 180000,
             "requests_used": 10, "tokens_used": 10500,
             "disabled": False, "exhausted_until": None},
            {"name": "gemini-gemma", "family": "gemini", "model": "gemma-4-31b-it",
             "daily_cap_requests": 14400, "daily_cap_tokens": None,
             "requests_used": 100, "tokens_used": 0,
             "disabled": False, "exhausted_until": None},
        ]})
    user = FakeUser(OWNER_ID, first_name="سيف")
    msg = FakeMessage("/stats", -100222, user)
    ctx = make_ctx(FakeBot(), {"settings": settings, "router": router})
    await h.on_stats(make_update(msg, user, -100222), ctx)
    assert msg.reply_text.called
    text = msg.reply_text.call_args.args[0]
    assert "1200" in text and "حصة الجروب" in text
    assert "الوضع: اقتصادي" in text and "(مثبت)" in text  # cheap + dwell held
    assert "المستخدمين النشطين: 2" in text
    assert "1050" in text and "2400" in text
    assert "Test: 5/100" in text
    assert "groq-20b" in text and "gemini-gemma" in text
    assert "الكاش" in text
    assert len(text.splitlines()) <= 20
