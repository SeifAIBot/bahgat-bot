"""Live status message (v0.8, edit-in-place since v0.9): one editable
bubble, spinner, finalised into the answer — never deleted."""
import asyncio
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import tg.handlers as h
from core.config import Settings

OWNER_ID = 1415214630


def test_status_lines_are_bahgat_voiced():
    # v1.9: the thinking bubble no longer announces processing — short
    # human lines ("ثواني...", "لحظة، جايلك حالًا.") cycled by frame.
    thinking = h.status_line("thinking")
    assert thinking[2:] in h._THINKING_LINES
    assert "بفكر" not in thinking
    assert "النت" in h.status_line("searching")
    assert "يوتيوب" in h.status_line("youtube")
    assert "بنزلها" in h.status_line("downloading")
    for stage in ("thinking", "searching", "youtube", "downloading"):
        line = h.status_line(stage)
        assert line.strip()
        assert line[0] in h._SPINNER_FRAMES
    # Unknown stage falls back to thinking; frames cycle.
    assert h.status_line("nope") == h.status_line("thinking")
    assert h.status_line("thinking", 0) != h.status_line("thinking", 1)


class FakeStatusMessage:
    def __init__(self):
        self.edit_text = AsyncMock()
        self.delete = AsyncMock()


class FakeStatusBot:
    username = "Bahgoti_bot"
    id = 9106462211

    def __init__(self, fail_send=False):
        self.fail_send = fail_send
        self.sent = []
        self.kwargs = []

    async def send_message(self, chat_id, text, **kwargs):
        if self.fail_send:
            raise RuntimeError("send failed")
        m = FakeStatusMessage()
        self.sent.append((chat_id, text, m))
        self.kwargs.append(kwargs)
        return m


async def test_status_start_send_edit_finalize():
    bot = FakeStatusBot()
    status = h._StatusMessage(bot, -100, reply_to_message_id=7)
    await status.start()
    assert status.live
    assert len(bot.sent) == 1
    # Progress bubbles must not ring the group (research note §2).
    assert bot.kwargs[0].get("disable_notification") is True
    assert bot.kwargs[0].get("reply_to_message_id") == 7
    await status.set_stage("searching")
    msg = bot.sent[0][2]
    assert msg.edit_text.await_count >= 1
    assert "النت" in msg.edit_text.await_args.args[0]
    # v0.9: the bubble is EDITED into the final answer, never deleted.
    assert await status.finalize("النتيجة: مفيش حاجة", parse_mode="HTML") is True
    assert status.finalized
    assert not status.live  # it is the answer now, not a status
    assert msg.delete.await_count == 0
    last_edit = msg.edit_text.await_args
    assert "النتيجة: مفيش حاجة" in last_edit.args[0]
    assert last_edit.kwargs.get("parse_mode") == "HTML"
    # Idempotent: a second finalize is a no-op (no extra edit).
    edits_before = msg.edit_text.await_count
    assert await status.finalize("again") is False
    assert msg.edit_text.await_count == edits_before


async def test_status_send_failure_never_raises():
    bot = FakeStatusBot(fail_send=True)
    status = h._StatusMessage(bot, -100)
    await status.start()  # must not raise — the turn continues without it
    assert not status.live
    await status.set_stage("searching")  # no-op
    assert await status.finalize("النتيجة") is False  # no-op, no bubble


async def test_status_spinner_cycles_frames(monkeypatch):
    monkeypatch.setattr(h, "_STATUS_SPIN_SECONDS", 0.05)
    bot = FakeStatusBot()
    status = h._StatusMessage(bot, -100)
    await status.start()
    await asyncio.sleep(0.3)
    await status.finalize("done")
    msg = bot.sent[0][2]
    texts = [c.args[0] for c in msg.edit_text.await_args_list]
    frames = {t[0] for t in texts}
    assert len(frames) >= 2  # the spinner actually cycled


# --- status cleanup when a turn raises (pipeline) ---------------------------

class FakeUser:
    def __init__(self, uid, first_name="Test", username="testuser"):
        self.id = uid
        self.first_name = first_name
        self.username = username
        self.is_bot = False


class FakeChat:
    def __init__(self, chat_id):
        self.id = chat_id
        self.send_message = AsyncMock()


class FakeMessage:
    def __init__(self, text, chat_id, user, message_id=1):
        self.text = text
        self.chat_id = chat_id
        self.message_id = message_id
        self.from_user = user
        self.reply_to_message = None
        self.chat = FakeChat(chat_id)
        self.reply_text = AsyncMock(return_value=self)


class RaisingRouter:
    async def chat(self, *a, **k):
        raise RuntimeError("llm down")


@pytest.fixture(autouse=True)
def reset_handler_state():
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


async def test_status_edited_into_error_when_llm_raises(settings, memory_fakes, monkeypatch, tmp_db):
    monkeypatch.setattr(
        "brain.memory.check_and_consume_quota",
        lambda u, c, owner_id=None, capacity_replies=None, active_users=None,
        quota_cfg=None: (True, ""), raising=False,
    )
    bot = FakeStatusBot()
    bot.send_chat_action = AsyncMock()
    bot.get_chat_member = AsyncMock()
    ctx = SimpleNamespace(
        bot=bot,
        application=SimpleNamespace(
            bot_data={"settings": settings, "router": RaisingRouter(), "yt_requests": {}}))
    user = FakeUser(999, first_name="Test")
    # v1.0: "بهجت عامل ايه" is a fast-path greeting now (no LLM, no
    # bubble), so the LLM-raises case uses a real question instead —
    # and a plain-chat turn never starts a bubble, so the error goes
    # out as a normal message, not as an edited bubble.
    msg = FakeMessage("بهجت اشرحلي الدايرة الكهربائية بشتغل ازاي", -1005812444791, user)
    update = SimpleNamespace(
        update_id=100, effective_message=msg, effective_user=user,
        effective_chat=FakeChat(-1005812444791), my_chat_member=None,
        callback_query=None)
    # on_group_message catches turn errors itself (logs them) — the turn
    # "fails" internally, so assert on the observable behaviour instead.
    await h.on_group_message(update, ctx)
    # No bubble went up for a plain-chat turn…
    assert len(bot.sent) == 0
    # …so the in-character error line goes out as a normal message.
    msg.reply_text.assert_called_once()
    assert "حصلت مشكلة تقنية" in msg.reply_text.await_args.args[0]
