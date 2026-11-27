"""v1.11: bank insult lines are INGREDIENTS, never standalone replies.

Seif's rule (2026-11-27 05:34 EET): when the bot answers an insult
with one of his lines (or any bank insult line), it must UNDERSTAND
the line and weave it into the middle of a fuller reply — the line
is never the whole reply alone.

Covered here:
(a) a picked insult/roast line appears INSIDE a longer reply, never
    as the whole reply (handler level, WeavingRouter);
(b) target/situation/member-safety still enforced at pick time
    (categorized matcher);
(c) owner gates intact (bank comebacks never fire at the owner;
    roasts never at the owner);
(d) LLM-failure fallback never sends the verbatim line alone —
    neither when the LLM is dead nor when the model stubbornly
    returns the line verbatim twice.
Also: the containment retry (a first draft that drops the line gets
one retry), and the non-insult categories staying verbatim (joke,
greeting) — the CHANGELOG decision.
"""
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from conftest import WeavingRouter, ingredient_of_call

import tg.handlers as h
from brain.prompt import bank_ingredient_block
from brain.reply_bank import (
    load_bank,
    match_reply_bank_categorized,
    reload_bank,
)

OWNER_ID = 1415214630
CHAT_ID = -1005812444791


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


class _RaisingRouter:
    def __init__(self):
        self.calls = []

    async def chat(self, *a, **k):
        self.calls.append((a, k))
        raise RuntimeError("llm down")


class _DropThenWeaveRouter:
    """First draft drops the ingredient (triggers the containment
    retry); the retry draft weaves it."""

    def __init__(self):
        self.calls = []

    async def chat(self, messages, hard=False, temperature=None, max_tokens=None, **kw):
        self.calls.append(messages)
        if len(self.calls) == 1:
            return ("مش عارف يا عم، يا غبي", "groq", 10)
        line = ingredient_of_call(messages)
        return (f"والله العظيم يا عم، {line}، وكمان كلام من عندي حواليه.",
                "groq", 10)


class _VerbatimRouter:
    """Returns the ingredient exactly as the reply, every call —
    simulates a model that refuses to weave."""

    def __init__(self):
        self.calls = []

    async def chat(self, messages, hard=False, temperature=None, max_tokens=None, **kw):
        self.calls.append(messages)
        line = ingredient_of_call(messages)
        return (line, "groq", 10)


def make_ctx(bot, bot_data):
    return SimpleNamespace(bot=bot, application=SimpleNamespace(bot_data=bot_data))


def make_update(msg, user, chat_id, update_id=100):
    return SimpleNamespace(
        update_id=update_id, effective_message=msg, effective_user=user,
        effective_chat=FakeChat(chat_id), my_chat_member=None, callback_query=None,
    )


@pytest.fixture(autouse=True)
def reset_handler_state(tmp_db):
    """tmp_db (conftest): points BOTH handlers' dedup DB (h.DB_PATH)
    and brain.memory at a throwaway DB — without it, _is_duplicate
    writes the test update_ids into the real data/bahgat.db and later
    runs silently drop the turns as duplicates (and a cached reply in
    the real DB would take the cache path instead of the router)."""
    reload_bank()
    for d in (h._last_reply_time, h._last_cooldown_notice, h._last_send, h._send_count,
              h._seen_callbacks, h._membership_cache, h._chat_locks,
              h._last_voice, h._last_anon_notice):
        d.clear()
    import brain.reply_bank as _bank
    _bank._last_used.clear()
    h._delete_state("muted_until")
    yield
    reload_bank()
    h._delete_state("muted_until")


@pytest.fixture
def memory_fakes(monkeypatch):
    def _get_member(uid):
        return {"user_id": uid, "username": "", "first_name": "Test",
                "notes": "", "mood": 30, "grudge": "",
                "updated_at": time.time()}

    monkeypatch.setattr(h, "get_member", _get_member)
    monkeypatch.setattr(h, "save_member", lambda m: None)
    monkeypatch.setattr(h, "add_message", lambda *a, **k: None)
    monkeypatch.setattr(h, "recent_messages", lambda chat_id, limit=8: [])
    monkeypatch.setattr("random.random", lambda: 0.99)  # no random voice


@pytest.fixture
def settings():
    from core.config import Settings
    return Settings(telegram_bot_token="x", owner_id=OWNER_ID, allowed_chat_ids="")


def _run_turn(monkeypatch, settings, text, router, user_id=777, chat_id=-100222,
              update_id=100):
    monkeypatch.setattr(
        "brain.memory.check_and_consume_quota",
        lambda u, c, owner_id=None, capacity_replies=None, active_users=None,
        quota_cfg=None: (True, ""), raising=False,
    )
    monkeypatch.setattr(h, "_search_grounding",
                        AsyncMock(return_value="[SEARCH FAILED] — مفيش نتائج موثوقة، متخترعش."))
    bot = FakeBot()
    ctx = make_ctx(bot, {"settings": settings, "router": router, "yt_requests": {}})
    user = FakeUser(user_id, first_name="Ahmed")
    msg = FakeMessage(text, chat_id, user)
    return ctx, bot, msg, user


def _entry_for_line(category, line):
    for e in load_bank()[category]:
        if e["line"] == line:
            return e
    raise AssertionError(f"line not in bank[{category}]: {line!r}")


def _final(msg):
    assert msg.reply_text.await_count >= 1, "no reply was sent"
    return msg.reply_text.await_args.args[0]


# --- (a) the line is woven into a longer reply, never the whole reply -------

async def test_insult_line_woven_into_longer_reply(
        memory_fakes, settings, monkeypatch):
    router = WeavingRouter()
    ctx, bot, msg, user = _run_turn(
        monkeypatch, settings, "يا بهجت انت حمار", router, update_id=1001)
    await h._on_group_message_inner(make_update(msg, user, -100222, update_id=1001), ctx)
    assert len(router.calls) == 1
    line = ingredient_of_call(router.calls[0])
    assert line is not None
    final = _final(msg)
    assert line in final and len(final) > len(line)
    assert final not in {e["line"] for e in load_bank()["insulted"]}
    _entry_for_line("insulted", line)


async def test_roast_line_woven_into_longer_reply(
        memory_fakes, settings, monkeypatch):
    router = WeavingRouter()
    ctx, bot, msg, user = _run_turn(
        monkeypatch, settings, "يا بهجت اشتم صلاح", router, update_id=1002)
    await h._on_group_message_inner(make_update(msg, user, -100222, update_id=1002), ctx)
    assert len(router.calls) == 1
    line = ingredient_of_call(router.calls[0])
    assert line is not None
    final = _final(msg)
    assert line in final and len(final) > len(line)
    assert final not in {e["line"] for e in load_bank()["roast"]}
    entry = _entry_for_line("roast", line)
    assert entry.get("target") is None
    assert entry.get("member_safe", True) is not False


# --- containment retry: a draft that drops the line gets one retry -----------

async def test_first_draft_dropping_line_gets_one_retry(
        memory_fakes, settings, monkeypatch):
    router = _DropThenWeaveRouter()
    ctx, bot, msg, user = _run_turn(
        monkeypatch, settings, "يا بهجت انت حمار", router, update_id=1003)
    await h._on_group_message_inner(make_update(msg, user, -100222, update_id=1003), ctx)
    assert len(router.calls) == 2
    line = ingredient_of_call(router.calls[0])
    assert line is not None
    # The retry call appends a user message carrying the
    # "you dropped the line" instruction (last message, not the system
    # prompt).
    retry_note = router.calls[1][-1]["content"]
    assert "لازم الرد يحتوي السطر ده بالظبط" in retry_note
    assert line in retry_note
    final = _final(msg)
    assert line in final and len(final) > len(line)


# --- (d) LLM-failure fallback never sends the verbatim line alone ------------

async def test_llm_down_never_sends_verbatim_line(
        memory_fakes, settings, monkeypatch):
    router = _RaisingRouter()
    ctx, bot, msg, user = _run_turn(
        monkeypatch, settings, "يا بهجت انت حمار", router, update_id=1004)
    await h._on_group_message_inner(make_update(msg, user, -100222, update_id=1004), ctx)
    final = _final(msg)
    assert final == h._TURN_ERROR
    assert final not in {e["line"] for e in load_bank()["insulted"]}


async def test_stubborn_model_returning_line_twice_gets_generic_fallback(
        memory_fakes, settings, monkeypatch):
    router = _VerbatimRouter()
    ctx, bot, msg, user = _run_turn(
        monkeypatch, settings, "يا بهجت انت حمار", router, update_id=1005)
    await h._on_group_message_inner(make_update(msg, user, -100222, update_id=1005), ctx)
    # 1 call when the picked line carries its own angry markers (no
    # voice regen; the standalone check replaces it locally), 2 when
    # the voice-check regen fires first — either way the LLM turn ran
    # and the line never goes out alone. The final reply is the point.
    assert len(router.calls) >= 1
    line = ingredient_of_call(router.calls[0])
    assert line is not None
    final = _final(msg)
    # The standalone check replaces the line with a generic fallback
    # (one of _INGREDIENT_FALLBACK_LINES) — never the bank line alone.
    assert final in h._INGREDIENT_FALLBACK_LINES
    assert final not in {e["line"] for e in load_bank()["insulted"]}
    assert final != line


# --- (b) pick-time filters still enforced -------------------------------------

def test_pick_family_line_never_for_member_target():
    # A family-insult roast line (member_safe: false) must never be
    # picked when the target is a group member. Fresh chat + user per
    # pick so the no-repeat window never forces a fallback.
    for i in range(20):
        pick = match_reply_bank_categorized(
            "يا بهجت اشتم محمد", chat_id=-100222 - i, user_id=777 + i,
            target_is_member=True)
        assert pick is not None
        category, line = pick
        assert category == "roast"
        entry = _entry_for_line("roast", line)
        assert entry.get("member_safe", True) is not False


def test_pick_situation_matches_the_insult():
    # "انت حمار" -> called-dumb pool; the picked ingredient always
    # carries that situation tag. Fresh chat + user per pick so the
    # no-repeat window (last 25 per chat, last 10 per user) never
    # forces a fallback to the general pool (only 4 called-dumb lines).
    for i in range(20):
        pick = match_reply_bank_categorized(
            "يا بهجت انت حمار", chat_id=-100222 - i, user_id=777 + i)
        assert pick is not None
        category, line = pick
        assert category == "insulted"
        entry = _entry_for_line("insulted", line)
        assert "called-dumb" in (entry.get("situations") or [])


def test_pick_target_specific_line_only_for_its_target():
    # A line tagged for السيسي fires only when السيسي is the target;
    # for صلاح only generic lines come back. Fresh chat + user per
    # pick so the no-repeat window never forces a fallback.
    for i in range(20):
        pick = match_reply_bank_categorized(
            "يا بهجت اشتم صلاح", chat_id=-100222 - i, user_id=777 + i)
        assert pick is not None
        category, line = pick
        assert category == "roast"
        entry = _entry_for_line("roast", line)
        assert entry.get("target") is None


# --- (c) owner gates intact ---------------------------------------------------

def test_bank_comeback_never_fires_at_owner():
    # Seif's decision (2026-11-27 05:32 EET): bank comebacks NEVER
    # fire at the owner — v1.11 keeps the gate exactly as it was.
    for _ in range(20):
        assert match_reply_bank_categorized(
            "يا بهجت انت حمار", chat_id=-100222, user_id=OWNER_ID,
            is_owner=True) is None


def test_roast_never_fires_at_owner():
    # A roast request naming the owner himself gets no bank line.
    for _ in range(20):
        assert match_reply_bank_categorized(
            "يا بهجت اشتم سيف", chat_id=-100222, user_id=777,
            target_is_owner=True) is None


# --- non-insult categories stay verbatim (CHANGELOG decision) -----------------

async def test_joke_stays_verbatim_no_llm(
        memory_fakes, settings, monkeypatch):
    router = _RaisingRouter()
    ctx, bot, msg, user = _run_turn(
        monkeypatch, settings, "بهجت نكته", router, update_id=1006)
    await h._on_group_message_inner(make_update(msg, user, -100222, update_id=1006), ctx)
    assert len(router.calls) == 0
    final = _final(msg)
    assert final in {e["line"] for e in load_bank()["joke_request"]}


async def test_greeting_stays_verbatim_no_llm(
        memory_fakes, settings, monkeypatch):
    router = _RaisingRouter()
    ctx, bot, msg, user = _run_turn(
        monkeypatch, settings, "بهجت صباح الخير", router, update_id=1007)
    await h._on_group_message_inner(make_update(msg, user, -100222, update_id=1007), ctx)
    assert len(router.calls) == 0
    final = _final(msg)
    assert final in {e["line"] for e in load_bank()["greeting"]}


# --- prompt block ---------------------------------------------------------------

def test_ingredient_block_carries_line_and_instruction():
    block = bank_ingredient_block("دعوة الشرموطة مستجابة")
    assert "دعوة الشرموطة مستجابة" in block
    assert "في نص الرد" in block
    assert "ممنوع تبعت السطر ده لوحده" in block
    assert "افهم السطر ده كويس" in block
