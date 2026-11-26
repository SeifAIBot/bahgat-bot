"""v0.5 handler tests — allowlist, quota, /stats, owner mute, insult-target
resolution (owner), YouTube callback requester check + file-id cache.

The v0.5 brain/tools APIs (check_and_consume_quota, get_cached_file, ...)
are added by parallel workstreams, so tests monkeypatch them onto
brain.memory when needed; handlers look them up dynamically.
"""
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import tg.handlers as h
from core.config import Settings

OWNER_ID = 1415214630


# --- fakes ------------------------------------------------------------------

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
        self.reply_video = AsyncMock(
            return_value=SimpleNamespace(
                audio=SimpleNamespace(file_id="NEWFID"),
                video=SimpleNamespace(file_id="NEWFID"),
            )
        )


class FakeBot:
    def __init__(self):
        self.username = "Bahgoti_bot"
        self.id = 9106462211
        self.send_chat_action = AsyncMock()
        self.get_chat_member = AsyncMock()


class FakeRouter:
    def __init__(self, reply="تمام يا عم"):
        self.reply = reply
        self.calls = []

    async def chat(self, messages, hard=False, temperature=None, max_tokens=None):
        self.calls.append(messages)
        return (self.reply, "groq", 10)


def make_ctx(bot, bot_data):
    app = SimpleNamespace(bot_data=bot_data)
    return SimpleNamespace(bot=bot, application=app)


def make_update(msg, user, chat_id, update_id=100):
    return SimpleNamespace(
        update_id=update_id,
        effective_message=msg,
        effective_user=user,
        effective_chat=FakeChat(chat_id),
        my_chat_member=None,
        callback_query=None,
    )


@pytest.fixture(autouse=True)
def reset_handler_state():
    """Module-level in-memory state + the real-DB mute must not leak between
    tests. brain.memory state lives in the real data/bahgat.db (not the tmp
    DB), so the mute is cleared here, before every test."""
    for d in (h._last_reply_time, h._last_cooldown_notice, h._last_send, h._send_count,
              h._seen_callbacks, h._membership_cache, h._chat_locks,
              h._last_voice, h._last_anon_notice):
        d.clear()
    h._delete_state("muted_until")
    yield
    h._delete_state("muted_until")


@pytest.fixture
def memory_fakes(monkeypatch):
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


@pytest.fixture
def pipeline_ctx(settings, memory_fakes, monkeypatch):
    # v0.7: the quota stub takes the new signature (owner_id,
    # capacity_replies, active_users, quota_cfg).
    monkeypatch.setattr(
        "brain.memory.check_and_consume_quota",
        lambda u, c, owner_id=None, capacity_replies=None, active_users=None,
        quota_cfg=None: (True, ""), raising=False,
    )
    bot = FakeBot()
    router = FakeRouter()
    ctx = make_ctx(bot, {"settings": settings, "router": router, "yt_requests": {}})
    return ctx, router


# --- pure helper: insult-target resolution ----------------------------------

def test_resolve_target_reply_to_owner():
    owner = FakeUser(OWNER_ID, first_name="سيف")
    tid, name, src = h.resolve_insult_target("بهجت اشتمه", reply_to_user=owner)
    assert (tid, name, src) == (OWNER_ID, "سيف", "reply")


def test_resolve_target_named_matches_recent_speaker():
    speakers = [{"user_id": 555, "first_name": "محمد"}]
    tid, name, src = h.resolve_insult_target(
        "بهجت اشتم محمد", recent_speakers=speakers
    )
    assert (tid, name, src) == (555, "محمد", "named")


def test_resolve_target_none():
    assert h.resolve_insult_target("بهجت ازيك") == (None, None, "none")


# --- allowlist ---------------------------------------------------------------

async def test_allowlist_blocks_llm(pipeline_ctx, tmp_db):
    ctx, router = pipeline_ctx
    ctx.application.bot_data["settings"] = Settings(
        telegram_bot_token="x", owner_id=OWNER_ID, allowed_chat_ids="-100111"
    )
    user = FakeUser(777, first_name="Ahmed")
    msg = FakeMessage("بهجت ازيك؟", -100222, user)
    await h._on_group_message_inner(make_update(msg, user, -100222), ctx)
    assert router.calls == []
    msg.reply_text.assert_not_called()


# --- quota -------------------------------------------------------------------

async def test_quota_denied_no_llm(pipeline_ctx, monkeypatch, tmp_db):
    ctx, router = pipeline_ctx
    monkeypatch.setattr(
        "brain.memory.check_and_consume_quota",
        lambda u, c, owner_id=None, capacity_replies=None, active_users=None,
        quota_cfg=None: (False, "fair share reached"), raising=False,
    )
    user = FakeUser(777, first_name="Ahmed")
    msg = FakeMessage("بهجت ازيك؟", -100222, user)
    await h._on_group_message_inner(make_update(msg, user, -100222), ctx)
    assert router.calls == []
    assert msg.reply_text.called
    sent = msg.reply_text.call_args.args[0]
    assert "كفاية كده النهاردة" in sent


# --- /stats ------------------------------------------------------------------

async def test_stats_non_owner_gets_nothing(settings, tmp_db):
    user = FakeUser(999, first_name="Stranger")
    msg = FakeMessage("/stats", -100222, user)
    ctx = make_ctx(FakeBot(), {"settings": settings})
    await h.on_stats(make_update(msg, user, -100222), ctx)
    msg.reply_text.assert_not_called()


async def test_stats_owner_gets_usage(settings, memory_fakes, monkeypatch, tmp_db):
    monkeypatch.setattr(
        "brain.memory.get_usage_today",
        lambda: {"per_user": {777: 5}, "group_total": 5, "by_chat": {-100222: 5}},
        raising=False,
    )
    # v0.7: /stats reads the live pool from the router (no more hardcoded
    # Groq 150k / Gemini 15 numbers) and per-user counts from usage.
    # fair_share_info is forced to None here so the test exercises the
    # plain-count fallback ("Test: 5"); the live fair-share line is
    # covered by test_cache_quota_v06 / test_router_handlers_v07.
    monkeypatch.setattr(
        "brain.memory.fair_share_info", lambda *a, **k: None, raising=False)
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
                    ]}

    user = FakeUser(OWNER_ID, first_name="سيف")
    msg = FakeMessage("/stats", -100222, user)
    ctx = make_ctx(FakeBot(), {"settings": settings, "router": StatsRouter()})
    await h.on_stats(make_update(msg, user, -100222), ctx)
    assert msg.reply_text.called
    text = msg.reply_text.call_args.args[0]
    assert "groq-20b" in text
    assert "حصة الجروب" in text and "1200" in text
    assert "الوضع: عادي" in text
    assert "Test: 5" in text  # per-user counts from get_usage_today()
    assert len(text.splitlines()) <= 20


# --- owner mute ---------------------------------------------------------------

async def test_owner_mute_then_silent(pipeline_ctx, tmp_db):
    ctx, router = pipeline_ctx
    owner = FakeUser(OWNER_ID, first_name="سيف")
    msg = FakeMessage("اسكت يا بهجت", -100222, owner)
    await h._on_group_message_inner(make_update(msg, owner, -100222, update_id=201), ctx)
    assert msg.reply_text.called
    assert "ههدى" in msg.reply_text.call_args.args[0]

    user = FakeUser(777, first_name="Ahmed")
    msg2 = FakeMessage("بهجت ازيك؟", -100222, user)
    await h._on_group_message_inner(make_update(msg2, user, -100222, update_id=202), ctx)
    assert router.calls == []
    msg2.reply_text.assert_not_called()

    # Leave the workspace clean: unmute again (mute state lives in the real DB).
    msg3 = FakeMessage("اتكلم يا بهجت", -100222, owner)
    await h._on_group_message_inner(make_update(msg3, owner, -100222, update_id=203), ctx)
    assert not h._is_muted()


# --- insult target: owner ------------------------------------------------------

async def test_insult_target_owner_in_system_prompt(pipeline_ctx, tmp_db):
    ctx, router = pipeline_ctx
    owner = FakeUser(OWNER_ID, first_name="سيف")
    reply_to = FakeMessage("هههه", -100222, owner)
    user = FakeUser(777, first_name="Ahmed")
    msg = FakeMessage("بهجت اشتم سيف", -100222, user, reply_to=reply_to)
    await h._on_group_message_inner(make_update(msg, user, -100222), ctx)
    # v1.3: "اشتم سيف" is a provoked turn (roast request) and the fake
    # router's fixed draft "تمام يا عم" is edgeless, so voice_check
    # flags soft_reply_to_provocation and the handler regenerates once.
    assert len(router.calls) == 2
    system = next(m["content"] for m in router.calls[0] if m["role"] == "system")
    assert "ممنوع تشتم سيف" in system


# --- YouTube callback ----------------------------------------------------------

def _callback_ctx(settings, bot_data_extra=None):
    bot = FakeBot()
    bot_data = {"settings": settings, "router": FakeRouter(), "yt_requests": {}}
    if bot_data_extra:
        bot_data.update(bot_data_extra)
    return make_ctx(bot, bot_data), bot


async def test_callback_wrong_user_rejected(settings, tmp_db):
    ctx, _bot = _callback_ctx(settings)
    chat_id, message_id, requester = -100222, 42, 777
    ctx.application.bot_data["yt_requests"] = {
        (chat_id, message_id, requester): {
            "query": "test", "url": "https://youtube.com/watch?v=x",
            "video_id": "x", "title": "t", "expires_at": time.time() + 600,
        }
    }
    qmsg = FakeMessage("choice", chat_id, FakeUser(requester), message_id=message_id)
    q = SimpleNamespace(
        id="cb-wrong-user-1", data="yt:video", from_user=FakeUser(888, first_name="Other"),
        message=qmsg, answer=AsyncMock(),
        edit_message_text=AsyncMock(), edit_message_reply_markup=AsyncMock(),
    )
    update = SimpleNamespace(callback_query=q)
    await h.on_callback(update, ctx)
    assert q.answer.called
    args, kwargs = q.answer.call_args
    assert "مش بتاعتك" in args[0]
    assert kwargs.get("show_alert") is True
    qmsg.reply_video.assert_not_called()


async def test_callback_requester_uses_file_id_cache(settings, monkeypatch, tmp_db):
    monkeypatch.setattr(
        "brain.memory.get_cached_file", lambda url, audio_only: "FILEID123", raising=False
    )
    ctx, _bot = _callback_ctx(settings)
    chat_id, message_id, requester = -100222, 43, 777
    ctx.application.bot_data["yt_requests"] = {
        (chat_id, message_id, requester): {
            "query": "test", "url": "https://youtube.com/watch?v=x",
            "video_id": "x", "title": "t", "expires_at": time.time() + 600,
        }
    }
    qmsg = FakeMessage("choice", chat_id, FakeUser(requester), message_id=message_id)
    q = SimpleNamespace(
        id="cb-cache-1", data="yt:video", from_user=FakeUser(requester),
        message=qmsg, answer=AsyncMock(),
        edit_message_text=AsyncMock(), edit_message_reply_markup=AsyncMock(),
    )
    update = SimpleNamespace(callback_query=q)
    await h.on_callback(update, ctx)
    qmsg.reply_video.assert_called_once()
    assert qmsg.reply_video.call_args.kwargs.get("video") == "FILEID123"
