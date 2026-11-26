"""YouTube pick-list (v0.8): search_query, list builders, pick callback."""
import json
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import tg.handlers as h
from core.config import Settings
from tools import youtube as yt

OWNER_ID = 1415214630


def _results(n=3):
    return [
        {"video_id": f"id{i}", "url": f"https://www.youtube.com/watch?v=id{i}",
         "title": f"MARWAN PABLO - EL HALAL | مروان بابلو - الحلال {i}",
         "duration": 231 + i,
         "thumbnail": f"https://i.ytimg.com/vi/id{i}/hqdefault.jpg"}
        for i in range(n)
    ]


def test_fmt_duration():
    assert h._fmt_duration(231) == "3:51"
    assert h._fmt_duration(61) == "1:01"
    assert h._fmt_duration(None) == "؟"
    assert h._fmt_duration("3:51") == "3:51"


def test_truncate_button():
    assert h._truncate_button("قصير") == "قصير"
    long = "MARWAN PABLO - EL HALAL | مروان بابلو - الحلال"
    t = h._truncate_button(long)
    assert len(t) <= 40 and t.endswith("…")


def test_pick_list_text_and_keyboard():
    results = _results(3)
    text = h._pick_list_text("مروان بابلو الحلال", results)
    assert text.startswith("• نتائج البحث ← مروان بابلو الحلال")
    for i, r in enumerate(results, 1):
        assert f"{i}. {r['title']}" in text
    kb = h._pick_list_keyboard(results)
    rows = kb.inline_keyboard
    assert len(rows) == 3
    for i, row in enumerate(rows):
        assert len(row) == 1
        assert row[0].callback_data == f"yt:pick:{i}"
        assert len(row[0].callback_data.encode()) <= 64


def test_parse_pick_callback():
    assert h._parse_pick_callback("yt:pick:2") == 2
    assert h._parse_pick_callback("yt:pick:0") == 0
    assert h._parse_pick_callback("yt:video") is None
    assert h._parse_pick_callback("yt:pick:x") is None
    assert h._parse_pick_callback("") is None


# --- tools.youtube.search_query ---------------------------------------------

class _FakeProc:
    def __init__(self, stdout):
        self.stdout = stdout


def test_search_query_parses_ytsearch(monkeypatch):
    payload = {"entries": [
        {"id": "abc", "title": "Song One", "duration": 200},
        {"id": "def", "title": "Song Two", "duration": None},
    ]}
    seen = {}

    def fake_run(args, timeout):
        seen["args"] = args
        return _FakeProc(json.dumps(payload))

    monkeypatch.setattr(yt, "_run_yt_dlp", fake_run)
    out = yt.search_query("مروان بابلو", limit=5)
    assert "ytsearch5:مروان بابلو" in seen["args"]
    assert "--flat-playlist" in seen["args"]
    assert "--" in seen["args"]
    assert len(out) == 2
    assert out[0]["url"] == "https://www.youtube.com/watch?v=abc"
    assert out[0]["duration"] == 200
    assert out[0]["thumbnail"] == "https://i.ytimg.com/vi/abc/hqdefault.jpg"
    assert out[1]["duration"] is None


def test_search_query_rejects_url_and_option():
    with pytest.raises(ValueError):
        yt.search_query("https://www.youtube.com/watch?v=x")
    with pytest.raises(ValueError):
        yt.search_query("-x")


# --- pick callback -----------------------------------------------------------

class FakePickMessage:
    def __init__(self, chat_id, message_id):
        self.chat_id = chat_id
        self.message_id = message_id
        self.reply_photo = AsyncMock(return_value=SimpleNamespace(message_id=99))
        self.delete = AsyncMock()


class FakeQuery:
    def __init__(self, data, message, user_id, qid="q1"):
        self.data = data
        self.message = message
        self.from_user = SimpleNamespace(id=user_id)
        self.id = qid
        self.answer = AsyncMock()
        self.edit_message_text = AsyncMock()


@pytest.fixture(autouse=True)
def reset_handler_state():
    for d in (h._seen_callbacks, h._chat_locks):
        d.clear()
    h._delete_state("muted_until")
    yield
    h._delete_state("muted_until")


@pytest.fixture
def settings():
    return Settings(telegram_bot_token="x", owner_id=OWNER_ID, allowed_chat_ids="")


def _pick_ctx(settings, state, message_id=5, requester=999):
    bot_data = {"settings": settings, "yt_requests": {
        (-100, message_id, requester): state}}
    return SimpleNamespace(
        bot=SimpleNamespace(username="Bahgoti_bot"),
        application=SimpleNamespace(bot_data=bot_data)), bot_data


def _pick_state(results, expires_in=600):
    return {"query": "مروان بابلو الحلال", "results": results,
            "expires_at": time.time() + expires_in}


async def test_pick_edits_list_into_text_choice_and_keeps_state_key(settings, tmp_db):
    ctx, bot_data = _pick_ctx(settings, _pick_state(_results(3)))
    msg = FakePickMessage(-100, 5)
    q = FakeQuery("yt:pick:1", msg, 999)
    update = SimpleNamespace(callback_query=q, update_id=1)
    await h._on_yt_pick_inner(update, ctx)
    q.answer.assert_awaited_once()
    # v0.9: the list message is EDITED into the text choice view (title +
    # duration + the two buttons) — no photo, no delete, no tombstone.
    msg.reply_photo.assert_not_awaited()
    msg.delete.assert_not_awaited()
    q.edit_message_text.assert_awaited_once()
    assert "الحلال 1" in q.edit_message_text.await_args.args[0]
    assert "(3:52)" in q.edit_message_text.await_args.args[0]
    rows = q.edit_message_text.await_args.kwargs["reply_markup"].inline_keyboard
    assert [b.callback_data for b in rows[0]] == ["yt:video", "yt:audio"]
    # State stays keyed on the SAME message id (the list message), now
    # pointing at the picked video.
    assert (-100, 5, 999) in bot_data["yt_requests"]
    assert bot_data["yt_requests"][(-100, 5, 999)]["url"] == \
        "https://www.youtube.com/watch?v=id1"


async def test_pick_without_thumbnail_still_edits_in_place(settings, tmp_db):
    results = _results(3)
    for r in results:
        r.pop("thumbnail", None)
    ctx, bot_data = _pick_ctx(settings, _pick_state(results))
    msg = FakePickMessage(-100, 5)
    q = FakeQuery("yt:pick:2", msg, 999)
    await h._on_yt_pick_inner(SimpleNamespace(callback_query=q, update_id=1), ctx)
    # Same message edited in place to the text choice view.
    q.edit_message_text.assert_awaited_once()
    edit_kwargs = q.edit_message_text.await_args.kwargs
    assert "الحلال 2" in q.edit_message_text.await_args.args[0]
    rows = edit_kwargs["reply_markup"].inline_keyboard
    assert [b.callback_data for b in rows[0]] == ["yt:video", "yt:audio"]
    # State updated in place (same message id), now pointing at the pick.
    assert bot_data["yt_requests"][(-100, 5, 999)]["url"] == \
        "https://www.youtube.com/watch?v=id2"


async def test_pick_wrong_user_rejected(settings, tmp_db):
    ctx, bot_data = _pick_ctx(settings, _pick_state(_results(3)))
    msg = FakePickMessage(-100, 5)
    q = FakeQuery("yt:pick:0", msg, 123)  # not the requester (999)
    await h._on_yt_pick_inner(SimpleNamespace(callback_query=q, update_id=1), ctx)
    q.answer.assert_awaited_once_with("دي مش بتاعتك يا عم", show_alert=True)
    msg.reply_photo.assert_not_awaited()
    q.edit_message_text.assert_not_awaited()
    assert (-100, 5, 999) in bot_data["yt_requests"]


async def test_pick_expired_state_rejected(settings, tmp_db):
    ctx, bot_data = _pick_ctx(settings, _pick_state(_results(3), expires_in=-10))
    msg = FakePickMessage(-100, 5)
    q = FakeQuery("yt:pick:0", msg, 999)
    await h._on_yt_pick_inner(SimpleNamespace(callback_query=q, update_id=1), ctx)
    q.answer.assert_awaited_once_with("الطلب ده خلص، ابعت تاني.", show_alert=True)
    msg.reply_photo.assert_not_awaited()
    q.edit_message_text.assert_not_awaited()
