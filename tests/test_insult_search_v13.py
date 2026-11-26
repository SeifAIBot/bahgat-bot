"""v1.3: an insult turn must NEVER run a web search.

Regression (live, Seif's phone, 2026-11-26 19:53 EET): Seif sent
"يا بهجت انتا حمار" and the bot answered with the search-empty line
(_SEARCH_EMPTY: "دورت يا عم وملقيتش حاجة عن الموضوع ده …"). An insult
turn ran a web search and then reported finding nothing.

Root causes, both fixed here:
1. brain/intent.py _INSULT_RE did not know "انتا" — the common Egyptian
   spelling of "انت" (trailing alif). looks_like_insult("يا بهجت انتا
   حمار") was False, so the reply-bank insulted fast path never fired,
   the mood never rose, and no grudge was recorded.
2. tg/handlers.py _run_llm_turn: the unknown-retry (v0.9) fired a search
   on ANY just_chat turn whose first LLM reply looked "unknown" — only
   voice intents were excluded (v1.1). The LLM's first reply to the
   unrecognised insult contained an unknown marker, the retry searched
   for "يا بهجت انتا حمار", found nothing, and the turn ended with
   _SEARCH_EMPTY. Both retry branches are now gated on insult turns
   (gating only the first would let the elif produce _SEARCH_EMPTY with
   no search at all — search_text is "" there, so there are no passages).

Also covered: detect_intent() routes insult turns to just_chat before
the search check, and the "دور" prefix refuses an insult remainder
("دور يا حمار" is an insult, not a search).
"""
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import tg.handlers as h
from brain.intent import (
    detect_intent,
    detect_prefix_mode,
    looks_like_insult,
    looks_like_insult_turn,
)
from core.config import Settings

OWNER_ID = 1415214630

# The exact live phrase, plus the variants from the v1.3 task.
INSULT_PHRASES = [
    "يا بهجت انتا حمار",   # exact live phrase — "انتا" was the miss
    "انت حمار يا بهجت",
    "يا بهجت يا حمار",
    "بهجت انت غبي",
    "انتا حمار",
    "بهجت انتا غبي",
    "يا بهجت انتا كلب",
]
ROAST_REQUESTS = [
    "يا بهجت اشتم صلاح",
    "اشتم السيسي",
]


# --- intent level -----------------------------------------------------------

@pytest.mark.parametrize("text", INSULT_PHRASES)
def test_insult_phrase_is_insult_not_search(text):
    assert looks_like_insult(text) is True
    assert looks_like_insult_turn(text) is True
    assert detect_intent(text) == "just_chat"
    assert detect_intent(text) != "search"


@pytest.mark.parametrize("text", ROAST_REQUESTS)
def test_roast_request_is_insult_turn_not_search(text):
    # A roast request has no insult word aimed at the bot, but it is
    # still an insult turn — and it must never be classified as search.
    assert looks_like_insult_turn(text) is True
    assert detect_intent(text) == "just_chat"


def test_insult_with_search_keyword_still_not_search():
    # "ايه اللي حصل" is a search keyword on its own; attached to an
    # insult it must not pull the turn into the search path.
    assert detect_intent("انت حمار، ايه اللي حصل") == "just_chat"
    assert detect_intent("يا بهجت انتا حمار ايه اللي حصل") == "just_chat"


def test_dawwar_prefix_with_insult_remainder_is_not_search():
    assert detect_prefix_mode("دور يا حمار") is None
    assert detect_intent("دور يا حمار") == "just_chat"


def test_real_search_still_works():
    # Negative controls: the guards above must not swallow real searches.
    assert detect_intent("بهجت سيرش علي حادثة الوراق") == "search"
    assert detect_intent("دور حادثة الوراق") == "search"
    assert detect_prefix_mode("دور حادثة الوراق") == ("search", "حادثه الوراق")
    assert looks_like_insult_turn("بهجت سيرش علي حادثة الوراق") is False
    assert looks_like_insult("يا ابن عمي") is False


# --- handler level (pipeline harness, modelled on test_search_one_turn_v09.py)
# The LLM's first reply is "unknown" ("مش عارف …") AND carries an angry
# marker ("يا غبي") so the v1.1 voice check passes and no regeneration
# call muddies the router-call count: exactly ONE router call, ZERO
# searches, and the first reply stands — never _SEARCH_EMPTY.

UNKNOWN_FIRST_REPLY = "مش عارف يا عم، يا غبي"


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
    """Replies in order; records every call."""

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
def _tmp_bank_db(monkeypatch, tmp_path):
    """Isolate the persisted bank-rotation window (v1.6 phase 2):
    _pick() records every served line in brain.memory's bot_state, so
    without this the window would leak between tests (and into the
    real data/bahgat.db)."""
    from brain import memory

    db = tmp_path / "bank-test.db"
    monkeypatch.setattr(memory, "DB_PATH", db)
    monkeypatch.setattr(memory, "_SCHEMA_DONE", False)
    memory.init_db()
    yield
    monkeypatch.setattr(memory, "_SCHEMA_DONE", False)


@pytest.fixture(autouse=True)
def reset_handler_state():
    for d in (h._last_reply_time, h._last_cooldown_notice, h._last_send, h._send_count,
              h._seen_callbacks, h._membership_cache, h._chat_locks,
              h._last_voice, h._last_anon_notice):
        d.clear()
    # The bank rotates its last-5-served lines per (chat, category) in a
    # module-global — clear it so a bank line served by another test file
    # cannot change which comeback this turn gets.
    import brain.reply_bank as _bank
    _bank._last_used.clear()
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


def _run_turn(monkeypatch, settings, text, router, grounding_calls):
    """Run one turn with a recording _search_grounding; return (ctx, bot, msg)."""
    _quota_ok(monkeypatch)

    async def _recording_grounding(query):
        grounding_calls.append(query)
        return "[SEARCH FAILED] — مفيش نتائج موثوقة، متخترعش."

    monkeypatch.setattr(h, "_search_grounding", _recording_grounding)
    ctx, bot = _pipeline_ctx(settings, router)
    user = FakeUser(777, first_name="Ahmed")
    msg = FakeMessage(text, -100222, user)
    return ctx, bot, msg, user


def _final_reply_text(msg):
    """The text actually sent for the turn (reply_text, no status bubble)."""
    assert msg.reply_text.await_count >= 1, "no reply was sent"
    return msg.reply_text.await_args.args[0]


async def test_live_phrase_bank_intercepts_no_llm_no_search(
        memory_fakes, settings, tmp_db, monkeypatch):
    # The exact live phrase, end to end: the reply-bank insulted fast
    # path answers it, so the LLM is never called and no search runs.
    grounding_calls = []
    router = ScriptedRouter([UNKNOWN_FIRST_REPLY])
    ctx, bot, msg, user = _run_turn(
        monkeypatch, settings, "يا بهجت انتا حمار", router, grounding_calls)
    await h._on_group_message_inner(make_update(msg, user, -100222, update_id=911), ctx)
    assert router.calls == []
    assert grounding_calls == []
    assert bot.sent_status == []  # no status bubble for an insult turn
    final = _final_reply_text(msg)
    assert final != h._SEARCH_EMPTY
    assert "ملقيتش حاجة" not in final


# Handler level only runs phrases that trigger the bot ("بهجت" in the
# text — a bare "انتا حمار" with no trigger is correctly ignored by
# _should_reply, and is covered at the intent level above).
HANDLER_PHRASES = [p for p in INSULT_PHRASES if "بهجت" in p]


@pytest.mark.parametrize("text", HANDLER_PHRASES)
async def test_insult_variants_never_search_at_handler_level(
        memory_fakes, settings, tmp_db, monkeypatch, text):
    # Every variant: no search grounding call, no _SEARCH_EMPTY reply.
    grounding_calls = []
    router = ScriptedRouter([UNKNOWN_FIRST_REPLY])
    ctx, bot, msg, user = _run_turn(
        monkeypatch, settings, text, router, grounding_calls)
    await h._on_group_message_inner(make_update(msg, user, -100222, update_id=912), ctx)
    assert grounding_calls == []
    final = _final_reply_text(msg)
    assert final != h._SEARCH_EMPTY
    assert "ملقيتش حاجة" not in final


async def test_insult_unknown_first_reply_keeps_first_reply_no_search(
        memory_fakes, settings, tmp_db, monkeypatch):
    # The gating itself, with the bank deliberately bypassed: the LLM's
    # first reply looks "unknown", which is exactly what used to trigger
    # the search retry. The turn must keep its first reply, run NO
    # search, and never produce _SEARCH_EMPTY.
    monkeypatch.setattr(h, "match_reply_bank", lambda *a, **k: None)
    grounding_calls = []
    router = ScriptedRouter([UNKNOWN_FIRST_REPLY])
    ctx, bot, msg, user = _run_turn(
        monkeypatch, settings, "يا بهجت انتا حمار", router, grounding_calls)
    await h._on_group_message_inner(make_update(msg, user, -100222, update_id=913), ctx)
    assert len(router.calls) == 1  # first call only — no search retry
    assert grounding_calls == []
    final = _final_reply_text(msg)
    assert final == UNKNOWN_FIRST_REPLY
    assert final != h._SEARCH_EMPTY


async def test_roast_request_unknown_first_reply_no_search(
        memory_fakes, settings, tmp_db, monkeypatch):
    # Same gate for a roast request ("اشتم X"): bank bypassed, first
    # reply unknown — still no search, still no _SEARCH_EMPTY.
    monkeypatch.setattr(h, "match_reply_bank", lambda *a, **k: None)
    grounding_calls = []
    router = ScriptedRouter([UNKNOWN_FIRST_REPLY])
    ctx, bot, msg, user = _run_turn(
        monkeypatch, settings, "يا بهجت اشتم صلاح", router, grounding_calls)
    await h._on_group_message_inner(make_update(msg, user, -100222, update_id=914), ctx)
    assert len(router.calls) == 1
    assert grounding_calls == []
    final = _final_reply_text(msg)
    assert final == UNKNOWN_FIRST_REPLY
    assert final != h._SEARCH_EMPTY
