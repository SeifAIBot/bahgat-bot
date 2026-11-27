"""v0.9: a search turn completes in one turn, in the status bubble.

Regression (Seif's video, 2026-11-26 03:24-03:27 EET): he asked
"سيرش على النت على حادثة الوراق" and the bot answered "يا عم أنا مش
جوجل، بس هدورلك" — then nothing arrived until he asked "ايه الحصل"
again (twice). Root causes, all fixed here:
1. "سيرش على النت" missed _SEARCH_WORDS, so no search ran before the
   first LLM call (see tests/test_intent.py).
2. The prompt TAUGHT the "مش جوجل، بس هدورلك" dodge (fixed in
   persona/bahgat/examples.md + brain/prompt.py).
3. The handler sent that promise as the final reply and ended the turn.
4. The status bubble was deleted and the answer sent as a new message;
   Seif's rule is the result lands IN the "استنى بفكر" message.

Also covered: the YouTube download callback (a tap on a photo choice
view died on edit_message_text before the download even started, so
neither video nor audio ever arrived — only the picture stayed).
"""
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import tg.handlers as h
from core.config import Settings

OWNER_ID = 1415214630
PASSAGE = ("[1] https://example.com/news — حادثة الوراق خبر طويل من صفحة "
           "موثوقة. " * 5)


# --- pure helpers -----------------------------------------------------------

def test_search_passages_parses_grounding():
    assert h._search_passages("[SEARCH FAILED] — مفيش نتائج موثوقة، متخترعش.") == []
    assert h._search_passages("") == []
    out = h._search_passages(
        "[1] https://a.example — نص أول طويل بما يكفي.\n"
        "[2] https://b.example — نص تاني.")
    assert len(out) == 2
    assert out[0]["url"] == "https://a.example"
    assert "نص أول" in out[0]["text"]


def test_search_fallback_reply_extractive_then_empty():
    reply = h._search_fallback_reply(PASSAGE)
    assert reply.startswith("بص يا سيدي، دورت ولقيت كده:")
    assert "حادثة الوراق خبر طويل" in reply
    assert "https://example.com/news" in reply
    assert "هدورلك" not in reply
    assert h._search_fallback_reply("[SEARCH FAILED] — مفيش نتائج.") in h._SEARCH_FAILURE_LINES
    assert all("هدورلك" not in line for line in h._SEARCH_FAILURE_LINES)
    assert h._SEARCH_EMPTY in h._SEARCH_FAILURE_LINES


# --- pipeline harness (FakeBot WITH send_message: edit-in-place path) -------

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


class FakeStatusMessage:
    def __init__(self, message_id=77):
        self.message_id = message_id
        self.edit_text = AsyncMock()
        self.delete = AsyncMock()


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
        self.sent_status = []

    async def send_message(self, chat_id, text, **kwargs):
        m = FakeStatusMessage()
        self.sent_status.append(m)
        return m


class ScriptedRouter:
    """Replies in order; records every call (messages + kwargs)."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    async def chat(self, messages, hard=False, temperature=None, max_tokens=None, **kw):
        self.calls.append(messages)
        reply = self.replies.pop(0) if self.replies else "تمام يا عم"
        return (reply, "groq", 10)


def make_ctx(bot, bot_data):
    return SimpleNamespace(bot=bot, application=SimpleNamespace(bot_data=bot_data))


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


def _pipeline_ctx(settings, router):
    bot = FakeBot()
    return make_ctx(bot, {"settings": settings, "router": router, "yt_requests": {}}), bot


def _quota_ok(monkeypatch):
    monkeypatch.setattr(
        "brain.memory.check_and_consume_quota",
        lambda u, c, owner_id=None, capacity_replies=None, active_users=None,
        quota_cfg=None: (True, ""), raising=False,
    )


def _last_status_edit(bot):
    """Text of the last edit on the status bubble (the final answer)."""
    assert bot.sent_status, "no status bubble was sent"
    msg = bot.sent_status[0]
    assert msg.edit_text.await_count >= 1
    return msg.edit_text.await_args.args[0]


# --- search endgame: one turn, in the bubble --------------------------------

async def test_search_question_answered_in_one_turn_in_the_bubble(
        memory_fakes, settings, tmp_db, monkeypatch):
    _quota_ok(monkeypatch)

    async def _fake_grounding(query):
        return PASSAGE

    monkeypatch.setattr(h, "_search_grounding", _fake_grounding)
    router = ScriptedRouter([
        "مش عارف يا عم",
        "بص يا سيدي، دورت في الأخبار ومفيش حاجة عن الوراق النهارده",
    ])
    ctx, bot = _pipeline_ctx(settings, router)
    user = FakeUser(777, first_name="Ahmed")
    msg = FakeMessage("بهجت سيرش على النت على حادثة الوراق", -100222, user)
    await h._on_group_message_inner(make_update(msg, user, -100222, update_id=901), ctx)
    # First reply was unknown -> ONE firm retry from the grounding.
    assert len(router.calls) == 2
    # The answer lands IN the status bubble (edit), not a new message.
    final = _last_status_edit(bot)
    assert "مفيش حاجة عن الوراق" in final
    assert "هدورلك" not in final
    msg.reply_text.assert_not_called()
    bot.sent_status[0].delete.assert_not_awaited()


async def test_search_empty_when_nothing_found(memory_fakes, settings, tmp_db, monkeypatch):
    _quota_ok(monkeypatch)

    async def _fake_grounding(query):
        return "[SEARCH FAILED] — مفيش نتائج موثوقة، متخترعش."

    monkeypatch.setattr(h, "_search_grounding", _fake_grounding)
    router = ScriptedRouter(["مش عارف يا عم"])
    ctx, bot = _pipeline_ctx(settings, router)
    user = FakeUser(777, first_name="Ahmed")
    msg = FakeMessage("بهجت سيرش على النت على حادثة الوراق", -100222, user)
    await h._on_group_message_inner(make_update(msg, user, -100222, update_id=902), ctx)
    # No passages -> no retry, the turn ends with the plain "found
    # nothing" line in the same turn (not a "هدورلك" promise).
    assert len(router.calls) == 1
    final = _last_status_edit(bot)
    # v1.9: the "found nothing" reply is a random pick from the
    # human-voiced search-failure pool.
    assert final in h._SEARCH_FAILURE_LINES
    assert "هدورلك" not in final
    msg.reply_text.assert_not_called()


async def test_stall_twice_then_extractive_fallback(
        memory_fakes, settings, tmp_db, monkeypatch):
    _quota_ok(monkeypatch)

    async def _fake_grounding(query):
        return PASSAGE

    monkeypatch.setattr(h, "_search_grounding", _fake_grounding)
    stall = "يا عم انا لسه قالك، بدور، استنير شويه لما اجيبلك الخلاصه"
    router = ScriptedRouter([stall, stall])
    ctx, bot = _pipeline_ctx(settings, router)
    user = FakeUser(777, first_name="Ahmed")
    msg = FakeMessage("بهجت سيرش على النت على حادثة الوراق", -100222, user)
    await h._on_group_message_inner(make_update(msg, user, -100222, update_id=903), ctx)
    assert len(router.calls) == 2  # first stall + one firm retry
    final = _last_status_edit(bot)
    assert "دورت ولقيت كده" in final
    assert "حادثة الوراق خبر طويل" in final
    assert "لسه" not in final
    msg.reply_text.assert_not_called()


# --- YouTube download callback: never silent --------------------------------

class FakeCallbackMessage(FakeMessage):
    def __init__(self, *a, photo=None, **kw):
        super().__init__(*a, **kw)
        self.photo = photo


def _callback_ctx(settings, state, message_id=42, requester=777):
    bot = FakeBot()
    bot_data = {"settings": settings, "router": ScriptedRouter(["تمام يا عم"]),
                "yt_requests": {(-100222, message_id, requester): state}}
    return make_ctx(bot, bot_data)


def _yt_state(expires_in=600):
    return {"query": "test", "url": "https://www.youtube.com/watch?v=x",
            "video_id": "x", "title": "t", "expires_at": time.time() + expires_in}


def _callback_query(data, message, user_id, qid="cb-v09"):
    return SimpleNamespace(
        id=qid, data=data, from_user=FakeUser(user_id), message=message,
        answer=AsyncMock(), edit_message_text=AsyncMock(),
        edit_message_caption=AsyncMock(), edit_message_reply_markup=AsyncMock(),
    )


async def test_callback_photo_choice_edits_caption_and_downloads(
        settings, tmp_db, tmp_path, monkeypatch):
    # v0.8 bug: the choice view was a PHOTO, and the callback called
    # edit_message_text on it — the Bot API rejects that, the callback
    # died before the download started, and the tap went silent.
    monkeypatch.setattr(
        "brain.memory.get_cached_file", lambda url, audio_only: None, raising=False)
    monkeypatch.setattr(
        "brain.memory.cache_file", lambda *a, **k: None, raising=False)

    req_dir = tmp_path / "dl"
    req_dir.mkdir()
    video_file = req_dir / "video.mp4"
    video_file.write_bytes(b"fake-video-bytes")
    monkeypatch.setattr(
        "tools.youtube.download", lambda url, audio_only: str(video_file))

    ctx = _callback_ctx(settings, _yt_state())
    qmsg = FakeCallbackMessage("choice", -100222, FakeUser(777), message_id=42,
                               photo=[SimpleNamespace(file_id="PHOTOID")])
    q = _callback_query("yt:video", qmsg, 777)
    await h.on_callback(SimpleNamespace(callback_query=q), ctx)
    q.answer.assert_awaited_once()
    # Progress + done go to the CAPTION (photo message), never to text
    # (edit_message_caption takes the text as the `caption` keyword).
    caption_calls = [c.kwargs.get("caption", "")
                     for c in q.edit_message_caption.await_args_list]
    assert any("بنزلها" in t for t in caption_calls)
    assert any("بعتها لك" in t for t in caption_calls)
    q.edit_message_text.assert_not_awaited()
    qmsg.reply_video.assert_called_once()
    assert not video_file.exists()  # cleaned up after sending


async def test_callback_download_failure_answers_in_chat(
        settings, tmp_db, monkeypatch):
    monkeypatch.setattr(
        "brain.memory.get_cached_file", lambda url, audio_only: None, raising=False)

    def _failing_download(url, audio_only):
        raise RuntimeError("yt-dlp failed")

    monkeypatch.setattr("tools.youtube.download", _failing_download)

    ctx = _callback_ctx(settings, _yt_state())
    qmsg = FakeCallbackMessage("choice", -100222, FakeUser(777), message_id=42)
    q = _callback_query("yt:audio", qmsg, 777)
    await h.on_callback(SimpleNamespace(callback_query=q), ctx)
    # The tap produces an in-character error IN the chat, never silence.
    # v1.9: the error is a random pick from the human-voiced download
    # failure pool — never programmer-talk.
    qmsg.reply_audio.assert_not_called()
    assert any(c.args[0] in h._DOWNLOAD_FAILURE_LINES
               for c in q.edit_message_text.await_args_list)


async def test_callback_text_choice_uses_text_edit(
        settings, tmp_db, monkeypatch):
    # v0.9 choice view is text again (pick edits the list in place): the
    # progress/done edits must go to the message text.
    monkeypatch.setattr(
        "brain.memory.get_cached_file", lambda url, audio_only: "FILEID123", raising=False)
    ctx = _callback_ctx(settings, _yt_state())
    qmsg = FakeCallbackMessage("choice", -100222, FakeUser(777), message_id=42)
    q = _callback_query("yt:video", qmsg, 777)
    await h.on_callback(SimpleNamespace(callback_query=q), ctx)
    qmsg.reply_video.assert_called_once()
    assert qmsg.reply_video.call_args.kwargs.get("video") == "FILEID123"
    text_calls = [c.args[0] for c in q.edit_message_text.await_args_list]
    assert any("بنزلها" in t for t in text_calls)
    assert any("بعتها لك" in t for t in text_calls)
    q.edit_message_caption.assert_not_awaited()
