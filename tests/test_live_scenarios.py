"""Live scenarios — Seif's real live-test phrases, automated (v1.6+).

Seif used to re-test every version by typing phrases in the Telegram
group and screenshotting replies. These tests feed the SAME phrases
through the REAL pipeline — detect_intent / detect_prefix_mode,
match_reply_bank, detect_*_situation, update_mood, _search_query,
check_reply / voice_check and tg.handlers._run_llm_turn — and assert
the behaviour he checked by hand, so a regression is caught here
before push instead of in the group.

Rules of this file:
- No real LLM calls: a ScriptedRouter answers in place of the
  providers (deterministic, no quota, no network). Everything else
  is the real code — no mocks for routing, intent, bank, mood or
  the handler's search/voice gates.
- No network, no Telegram sends: web search, YouTube search and
  voice synthesis are stubbed at the handler boundary
  (_search_grounding / _search_youtube / _try_send_voice) because
  they are I/O, not logic. The assertions are on what the pipeline
  DOES with their results.
- The persisted bank window + bot DB are isolated per test (tmp DBs),
  so runs never leak into data/bahgat.db or into each other.
- Handler tests use the REAL test-group chat id (-1005812444791)
  and the real bot username, but every send is a fake: nothing
  leaves this process.
"""
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from conftest import WeavingRouter, ingredient_of_call

import tg.handlers as h
from brain import memory
from brain.intent import (
    detect_insult_situation,
    detect_intent,
    detect_prefix_mode,
    detect_roast_situation,
    looks_like_insult_turn,
    looks_like_opinion_ask,
)
from brain.mood import SITUATION_MOOD_BUMP, update_mood
from brain.reply_bank import load_bank, match_reply_bank, reload_bank
from brain.verify import (
    BANNED,
    _SELF_BOT_DENIAL,
    check_reply,
    contains_family,
    contains_self_bot_admission,
    voice_check,
)
from core.config import Settings
from tg.handlers import _search_query

OWNER_ID = 1415214630
CHAT_ID = -1005812444791  # real test group "Bahgat bot" (fake sends only)
BOT_USERNAME = "Bahgoti_bot"

# --- Seif's exact live phrases -------------------------------------------
# From the 2026-11-26 19:53 EET live test (screenshot) and the
# follow-ups he asked for after it.
LIVE_INSULT = "يا بهجت انتا حمار"
LIVE_FAMILY_ATTACK = "يا بهجت يا ابن الكلب"
LIVE_ROAST_SALAH = "يا بهجت اشتم صلاح"
LIVE_ROAST_SISI = "يا بهجت اشتم السيسي"
LIVE_OPINION = "ايه رأيك في التعدد"
LIVE_ARE_YOU_BOT = "انت بوت؟"
LIVE_ARE_YOU_AI = "انت ذكاء اصطناعي؟"
LIVE_JOKE = "قولي نكته"
LIVE_SONG = "عايز اغنية مروان موسي الخلاصه"
LIVE_SEARCH = "دور حادثة الوراق"
LIVE_HAAT = "هات اغنية مروان موسي الخلاصه"
LIVE_VOICE = "قول اهلا في فويس نوت"
LIVE_FOLLOWUP = "ايه الحصل"
WARAK_TURN = "عايز اعرف ايه الحصل في حادثة الوراق المهاردة"


# --- fixtures (harness modelled on tests/test_insult_search_v13.py) --------

@pytest.fixture(autouse=True)
def _tmp_bank_db(monkeypatch, tmp_path):
    """Isolate the persisted bank-rotation window (v1.6 phase 2)."""
    db = tmp_path / "bank-test.db"
    monkeypatch.setattr(memory, "DB_PATH", db)
    monkeypatch.setattr(memory, "_SCHEMA_DONE", False)
    memory.init_db()
    yield
    monkeypatch.setattr(memory, "_SCHEMA_DONE", False)


@pytest.fixture(autouse=True)
def _reset_bank_state():
    reload_bank()
    yield
    reload_bank()


@pytest.fixture(autouse=True)
def reset_handler_state():
    for d in (h._last_reply_time, h._last_cooldown_notice, h._last_send,
              h._send_count, h._seen_callbacks, h._membership_cache,
              h._chat_locks, h._last_voice, h._last_anon_notice):
        d.clear()
    import brain.reply_bank as _bank
    _bank._last_used.clear()
    h._delete_state("muted_until")
    yield
    h._delete_state("muted_until")


@pytest.fixture
def memory_fakes(monkeypatch):
    """Capture saved members + history; no real DB reads for members."""
    saved = {}
    history = []

    def _get_member(uid):
        return {"user_id": uid, "username": "", "first_name": "Test",
                "notes": "", "mood": 30, "grudge": "",
                "updated_at": time.time()}

    def _save_member(m):
        saved[m["user_id"]] = dict(m)

    monkeypatch.setattr(h, "get_member", _get_member)
    monkeypatch.setattr(h, "save_member", _save_member)
    monkeypatch.setattr(h, "add_message", lambda *a, **k: history.append(a))
    monkeypatch.setattr(h, "recent_messages", lambda chat_id, limit=8: [])
    monkeypatch.setattr("random.random", lambda: 0.99)  # no random voice
    return {"saved": saved, "history": history}


@pytest.fixture
def settings():
    return Settings(telegram_bot_token="x", owner_id=OWNER_ID,
                    allowed_chat_ids="")


class FakeUser:
    def __init__(self, uid, first_name="Test", username="testuser",
                 is_bot=False):
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
        self.username = BOT_USERNAME
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

    async def chat(self, messages, hard=False, temperature=None,
                   max_tokens=None, **kw):
        self.calls.append(messages)
        reply = self.replies.pop(0) if self.replies else "تمام يا عم"
        return (reply, "groq", 10)


def make_ctx(bot, bot_data):
    return SimpleNamespace(bot=bot,
                           application=SimpleNamespace(bot_data=bot_data))


def make_update(msg, user, chat_id, update_id=100):
    return SimpleNamespace(
        update_id=update_id, effective_message=msg, effective_user=user,
        effective_chat=FakeChat(chat_id), my_chat_member=None,
        callback_query=None,
    )


def _quota_ok(monkeypatch):
    monkeypatch.setattr(
        "brain.memory.check_and_consume_quota",
        lambda u, c, owner_id=None, capacity_replies=None, active_users=None,
        quota_cfg=None: (True, ""), raising=False,
    )


def _grounding_stub(monkeypatch, calls, text=None):
    """Record every _search_grounding call; return one long passage."""
    if text is None:
        text = ("[1] https://example.com/news — خبر مهم عن الموضوع، "
                "تفاصيل كثيرة عن الحادثة وما جرى فيها. " * 8)

    async def _g(query):
        calls.append(query)
        return text

    monkeypatch.setattr(h, "_search_grounding", _g)


def _yt_results(n=3):
    return [
        {"video_id": f"id{i}",
         "url": f"https://www.youtube.com/watch?v=id{i}",
         "title": f"مروان موسي - الخلاصه {i}", "duration": 200 + i}
        for i in range(n)
    ]


def _yt_stub(monkeypatch, calls, n=3):
    async def _s(query, limit=5):
        calls.append(query)
        return _yt_results(n)

    monkeypatch.setattr(h, "_search_youtube", _s)


async def _run_turn(monkeypatch, settings, text, router, *,
                    chat_id=CHAT_ID, user_id=777, update_id=100,
                    reply_to=None):
    """One full turn through _on_group_message_inner (real pipeline,
    fake sends). Returns (ctx, bot, msg, user)."""
    _quota_ok(monkeypatch)
    bot = FakeBot()
    ctx = make_ctx(bot, {"settings": settings, "router": router,
                         "yt_requests": {}})
    user = FakeUser(user_id, first_name="Ahmed")
    msg = FakeMessage(text, chat_id, user, reply_to=reply_to)
    await h._on_group_message_inner(
        make_update(msg, user, chat_id, update_id=update_id), ctx)
    return ctx, bot, msg, user


def _entry_for_line(category, line):
    return next(e for e in load_bank()[category] if e["line"] == line)


def _last_status_edit(bot):
    """Text of the last edit to the (single) status bubble, or None."""
    if not bot.sent_status:
        return None
    m = bot.sent_status[0]
    if m.edit_text.await_count == 0:
        return None
    return m.edit_text.await_args.args[0]


# --- 1. routing: insult turns never search ---------------------------------

INSULT_TURNS = [
    LIVE_INSULT,                    # exact live phrase — "انتا" was the miss
    "انت حمار يا بهجت",
    "يا بهجت يا حمار",
    "بهجت انت غبي",
    "يا بهجت انتا غبي",
    "يا بهجت انتا كلب",
    LIVE_FAMILY_ATTACK,
    "يا بهجت هقتلك",
    "انت حمار، ايه اللي حصل",      # insult + a search keyword
    "يا بهجت انتا حمار ايه اللي حصل",
    "يا بهجت اشتم صلاح",           # roast request: also an insult turn
    "اشتم السيسي",
    "دور يا حمار",                 # "دور" prefix + insult remainder
]


@pytest.mark.parametrize("text", INSULT_TURNS)
def test_insult_turn_never_routes_to_search(text):
    assert looks_like_insult_turn(text) is True
    assert detect_intent(text) == "just_chat"
    assert detect_intent(text) != "search"


def test_dawwar_min_is_not_a_search():
    # "دور مين؟" is "whose turn is it?" — not a web search.
    assert detect_prefix_mode("دور مين؟") is None
    assert detect_intent("دور مين؟") == "just_chat"
    assert detect_prefix_mode("يا بهجت دور مين؟") is None
    assert detect_intent("يا بهجت دور مين؟") == "just_chat"


# --- 2. routing: Seif's prefix modes + intents ------------------------------

@pytest.mark.parametrize("text,mode,rest", [
    (LIVE_SEARCH, "search", "حادثه الوراق"),
    (LIVE_HAAT, "youtube", "اغنيه مروان موسي الخلاصه"),
    (LIVE_VOICE, "voice", "اهلا في فويس نوت"),
    (LIVE_JOKE, "voice", "نكته"),
])
def test_prefix_modes(text, mode, rest):
    assert detect_prefix_mode(text) == (mode, rest)
    assert detect_intent(text) == mode


def test_intent_modes():
    assert detect_intent(LIVE_SONG) == "youtube"
    assert detect_intent("يا بهجت " + LIVE_SONG) == "youtube"
    assert detect_intent(LIVE_JOKE) == "voice"  # bare "قولي نكته"
    assert detect_intent(LIVE_OPINION) == "just_chat"
    assert looks_like_opinion_ask(LIVE_OPINION) is True
    # A question ABOUT a song is not a play request.
    assert detect_intent("يا بهجت ايه رايك في اغنية مروان موسي") == "just_chat"


def test_ya_vocative_prefix_layer():
    # FIXED (v1.7): the prefix layer skips a leading "يا" vocative, so
    # Seif's usual "يا بهجت ..." form fires the prefix — the first
    # content word is the prefix word, and the remainder is clean (no
    # "يا بهجت" in it). The joke goes out as a voice note, and the
    # search grounds on the bare query, not the raw text.
    assert detect_prefix_mode("يا بهجت قولي نكته") == ("voice", "نكته")
    assert detect_intent("يا بهجت قولي نكته") == "voice"
    assert detect_prefix_mode("يا بهجت قول اهلا") == ("voice", "اهلا")
    assert detect_prefix_mode("يا بهجت هات اغنية مروان موسي") == (
        "youtube", "اغنيه مروان موسي")
    assert detect_prefix_mode("يا بهجت دور حادثة الوراق") == (
        "search", "حادثه الوراق")
    # Vocative without "بهجت" at all ("يا قول ...").
    assert detect_prefix_mode("يا قولي نكته") == ("voice", "نكته")
    assert detect_prefix_mode("يا دور حادثة الوراق") == (
        "search", "حادثه الوراق")
    # Only the LEADING "يا" is stripped: mid-sentence "يا" stays in
    # the remainder, and a bare vocative with no prefix word after it
    # is still normal chat.
    assert detect_prefix_mode("قول يا بهجت نكته") == ("voice", "يا نكته")
    assert detect_prefix_mode("يا بهجت") is None
    assert detect_prefix_mode("يا") is None
    assert detect_prefix_mode("يا بهجت عامل ايه") is None
    assert detect_intent("يا بهجت عامل ايه") == "just_chat"
    # The no-يا forms still fire exactly as before.
    assert detect_prefix_mode("بهجت قولي نكته") == ("voice", "نكته")
    assert detect_prefix_mode("بهجت قول اهلا") == ("voice", "اهلا")
    assert detect_prefix_mode("بهجت هات اغنية مروان موسي") == (
        "youtube", "اغنيه مروان موسي")
    assert detect_prefix_mode("بهجت دور حادثة الوراق") == (
        "search", "حادثه الوراق")


# --- 3. follow-up topic inheritance ------------------------------------------

def test_followup_inherits_waraq_topic():
    history = [{"role": "user",
                "content": f"[Seif Allah Mo]: {WARAK_TURN}"}]
    q = _search_query(LIVE_FOLLOWUP, history)
    assert "الوراق" in q
    assert LIVE_FOLLOWUP in q
    # And a bare follow-up with no topic in history searches as-is.
    assert _search_query(LIVE_FOLLOWUP, []) == LIVE_FOLLOWUP


# --- 4. situation detection: priority order ----------------------------------
# Code order: family-attacked > threatened > repeated-insult > mocked >
# called-dumb > sworn-at > dismissed > general. Each case carries two
# signals; the winner must be the higher-priority one.

_SITUATION_PRIORITY = [
    ("يا بهجت يا ابن الكلب هقتلك", "family-attacked"),   # family > threat
    ("يا بهجت هقتلك يا حمار يا حمار", "threatened"),     # threat > repeated
    ("يا بهجت يا حمار يا حمار ههههه", "repeated-insult"),  # repeated > mocked
    ("ههههه يا بهجت انت حمار", "mocked"),                # mocked > called-dumb
    ("يا بهجت انت حمار يا معرص", "called-dumb"),         # called-dumb > sworn-at
    ("يا بهجت يا معرص اخرس", "sworn-at"),                # sworn-at > dismissed
    ("يا بهجت انت تافه", "dismissed"),
    ("يا ابن عمي عامل ايه", "general"),                  # friendly, no situation
]


@pytest.mark.parametrize("text,expected", _SITUATION_PRIORITY)
def test_situation_priority(text, expected):
    assert detect_insult_situation(text) == expected, text


def test_roast_situation_detection():
    assert detect_roast_situation("اشتم محمد") == "general"
    assert detect_roast_situation("اشتم محمد عشان بيتباهى") == "arrogant"
    assert detect_roast_situation("اشتم محمد عشان غبي") == "stupid-statement"
    assert detect_roast_situation("اشتم محمد عشان جبان") == "cowardly"
    assert detect_roast_situation("اشتم محمد عشان بيزن") == "annoying"
    assert detect_roast_situation("اشتم محمد عشان شرموط") == "perv"


# --- 5. mood bumps by situation ----------------------------------------------

_MOOD_EXPECTED = {
    "family-attacked": 90,   # 30 + 60
    "threatened": 80,        # 30 + 50
    "repeated-insult": 80,   # 30 + 50
    "sworn-at": 75,          # 30 + 45
    "called-dumb": 70,       # 30 + 40
    "general": 70,           # 30 + 40
    "dismissed": 65,         # 30 + 35
    "mocked": 60,            # 30 + 30
}


def test_mood_bump_by_situation_table():
    for situation, expected in _MOOD_EXPECTED.items():
        assert update_mood(30, True,
                           insult_bump=SITUATION_MOOD_BUMP[situation]) == expected
    # A family attack stings more than a mild mock; the table is ordered.
    bumps = [SITUATION_MOOD_BUMP[s] for s in
             ("family-attacked", "threatened", "repeated-insult", "sworn-at",
              "called-dumb", "dismissed", "mocked")]
    assert bumps == sorted(bumps, reverse=True)


# --- 6. member safety (bank + post-check) -------------------------------------

def test_insulted_pool_never_carries_family_lines():
    # The comeback target is always the sender (a member): the whole
    # insulted pool must be member-safe by construction.
    assert all(e.get("member_safe", True) is not False
               for e in load_bank()["insulted"])


def test_check_reply_strips_family_for_members_keeps_for_outsiders():
    line = "يا معفن، امك اللي ربتك كده."
    assert contains_family(line) is True
    ok, cleaned = check_reply(line, insult_level="personal_only",
                              owner_id=OWNER_ID)
    assert ok is False
    assert not contains_family(cleaned)
    ok, kept = check_reply(line, insult_level="full", owner_id=OWNER_ID)
    assert ok is True and kept == line


# --- 7. roast targeting (bank level) ------------------------------------------

def _draws(text, n, **kwargs):
    return {match_reply_bank(text, chat_id=CHAT_ID, **kwargs)
            for _ in range(n)} - {None}


def test_salah_roast_is_generic_only():
    # Exact live bug: "اشتم صلاح" served ro-21 (a Sisi line). صلاح gets
    # generic lines only — never a Sisi-targeted line, never the Quran line.
    generic = {e["line"] for e in load_bank()["roast"]
               if e.get("target") is None}
    seen = _draws("اشتم صلاح", 60, target_is_member=False)
    assert seen, "roast must still answer for صلاح"
    assert seen <= generic
    assert "عاوز يغير في القرآن يا متناك؟" not in seen
    assert not any("السيسي" in line for line in seen)


def test_sisi_roast_is_sisi_or_generic_only():
    generic = {e["line"] for e in load_bank()["roast"]
               if e.get("target") is None}
    sisi = {e["line"] for e in load_bank()["roast"]
            if e.get("target") == "السيسي"}
    seen = _draws("اشتم السيسي", 60, target_is_member=False)
    assert seen, "roast must still answer for السيسي"
    assert seen <= generic | sisi
    assert seen & sisi, "Sisi-targeted lines must stay reachable for السيسي"
    assert "عاوز يغير في القرآن يا متناك؟" in seen


def test_roast_member_target_is_person_only():
    safe_generic = {e["line"] for e in load_bank()["roast"]
                    if e.get("target") is None
                    and e.get("member_safe", True) is not False}
    for _ in range(30):
        line = match_reply_bank("يا بهجت اشتم محمد", chat_id=CHAT_ID,
                                target_is_member=True)
        assert line in safe_generic


def test_roast_non_member_may_get_family_lines():
    # Non-members may get the full range, family lines included.
    generic = {e["line"] for e in load_bank()["roast"]
               if e.get("target") is None}
    family_generic = {e["line"] for e in load_bank()["roast"]
                      if e.get("target") is None
                      and e.get("member_safe", True) is False}
    assert family_generic, "no family lines in the generic roast pool"
    seen = _draws("اشتم صلاح", 60, target_is_member=False)
    assert seen <= generic
    assert seen & family_generic


# --- 8. contextual comeback selection (bank level) ----------------------------

@pytest.mark.parametrize("text,situation", [
    ("يا بهجت انت حمار", "called-dumb"),
    ("يا بهجت يا ابن الكلب", "family-attacked"),
    ("ههههه يا بهجت انت حمار", "mocked"),
    ("يا بهجت هقتلك", "threatened"),
    ("يا بهجت يا حمار يا حمار", "repeated-insult"),
    ("يا بهجت يا معرص", "sworn-at"),
    ("يا بهجت اخرس", "dismissed"),
])
def test_insulted_comeback_matches_situation(text, situation):
    pool = {e["line"] for e in load_bank()["insulted"]
            if situation in (e.get("situations") or [])}
    assert pool, situation
    line = match_reply_bank(text, chat_id=CHAT_ID, user_id=7)
    assert line in pool, (text, line)


# --- 9. handler level: Seif's live phrases end to end ------------------------

async def test_live_insult_phrase_end_to_end(
        memory_fakes, settings, tmp_db, monkeypatch):
    # The exact live phrase: v1.11 — the bank comeback is an
    # INGREDIENT now, not a standalone reply: the LLM turn runs once,
    # the system prompt carries the picked line in a [BANK LINE] block,
    # and the final reply weaves the line into a fuller reply. Mood
    # 30 -> 70 (called-dumb +40), no search, no status bubble.
    grounding_calls = []
    _grounding_stub(monkeypatch, grounding_calls)
    router = WeavingRouter()
    ctx, bot, msg, user = await _run_turn(
        monkeypatch, settings, LIVE_INSULT, router, update_id=901)
    assert len(router.calls) == 1
    assert grounding_calls == []
    assert bot.sent_status == []
    line = ingredient_of_call(router.calls[0])
    assert line is not None, "no [BANK LINE] ingredient in the LLM call"
    final = msg.reply_text.await_args.args[0]
    assert final != h._SEARCH_EMPTY
    assert "ملقيتش حاجة" not in final
    assert line in final and len(final) > len(line)
    entry = _entry_for_line("insulted", line)
    assert "called-dumb" in (entry.get("situations") or [])
    assert memory_fakes["saved"][777]["mood"] == 70


async def test_live_family_attack_end_to_end(
        memory_fakes, settings, tmp_db, monkeypatch):
    # Family attack at the bot: v1.11 — the comeback from the
    # family-attacked pool is an ingredient in the LLM turn, mood
    # 30 -> 90 (+60), and the picked line is still member-safe (the
    # insulted pool never serves family lines at members).
    grounding_calls = []
    _grounding_stub(monkeypatch, grounding_calls)
    router = WeavingRouter()
    ctx, bot, msg, user = await _run_turn(
        monkeypatch, settings, LIVE_FAMILY_ATTACK, router, update_id=902)
    assert len(router.calls) == 1
    assert grounding_calls == []
    line = ingredient_of_call(router.calls[0])
    assert line is not None, "no [BANK LINE] ingredient in the LLM call"
    final = msg.reply_text.await_args.args[0]
    assert line in final and len(final) > len(line)
    entry = _entry_for_line("insulted", line)
    assert "family-attacked" in (entry.get("situations") or [])
    assert entry.get("member_safe", True) is not False
    assert memory_fakes["saved"][777]["mood"] == 90


async def test_no_repeat_two_insults_get_different_comebacks(
        memory_fakes, settings, tmp_db, monkeypatch):
    # Same phrase twice in the same chat (two users, to dodge the 10s
    # per-user pacing): the no-repeat window must pick two different
    # ingredient lines from the same situation pool — v1.11, the two
    # LLM turns each carry a different [BANK LINE].
    grounding_calls = []
    _grounding_stub(monkeypatch, grounding_calls)
    router = WeavingRouter()
    _, _, msg1, _ = await _run_turn(
        monkeypatch, settings, "يا بهجت انت حمار", router,
        user_id=777, update_id=903)
    _, _, msg2, _ = await _run_turn(
        monkeypatch, settings, "يا بهجت انت حمار", router,
        user_id=778, update_id=904)
    r1 = msg1.reply_text.await_args.args[0]
    r2 = msg2.reply_text.await_args.args[0]
    assert r1 != r2
    line1 = ingredient_of_call(router.calls[0])
    line2 = ingredient_of_call(router.calls[1])
    assert line1 is not None and line2 is not None
    assert line1 != line2
    pool = {e["line"] for e in load_bank()["insulted"]
            if "called-dumb" in (e.get("situations") or [])}
    assert line1 in pool and line2 in pool
    assert line1 in r1 and line2 in r2
    assert len(router.calls) == 2 and grounding_calls == []


async def test_roast_salah_handler_end_to_end(
        memory_fakes, settings, tmp_db, monkeypatch):
    # "اشتم صلاح": v1.11 — the bank roast is an ingredient in the LLM
    # turn: generic member-safe line only, never the Sisi Quran line.
    grounding_calls = []
    _grounding_stub(monkeypatch, grounding_calls)
    router = WeavingRouter()
    ctx, bot, msg, user = await _run_turn(
        monkeypatch, settings, LIVE_ROAST_SALAH, router, update_id=905)
    assert len(router.calls) == 1
    assert grounding_calls == []
    line = ingredient_of_call(router.calls[0])
    assert line is not None, "no [BANK LINE] ingredient in the LLM call"
    final = msg.reply_text.await_args.args[0]
    assert line in final and len(final) > len(line)
    entry = _entry_for_line("roast", line)
    assert entry.get("target") is None
    assert entry.get("member_safe", True) is not False
    assert "القرآن" not in final


async def test_roast_sisi_handler_end_to_end(
        memory_fakes, settings, tmp_db, monkeypatch):
    # "اشتم السيسي": v1.11 — the bank roast is an ingredient in the LLM
    # turn: Sisi-targeted or generic lines only. 30 fresh chats: at
    # least one Sisi-targeted ingredient must appear.
    grounding_calls = []
    _grounding_stub(monkeypatch, grounding_calls)
    router = WeavingRouter()
    seen_targets = set()
    for i in range(30):
        ctx, bot, msg, user = await _run_turn(
            monkeypatch, settings, LIVE_ROAST_SISI, router,
            chat_id=CHAT_ID - i, user_id=9000 + i, update_id=910 + i)
        line = ingredient_of_call(router.calls[i])
        assert line is not None, "no [BANK LINE] ingredient in the LLM call"
        final = msg.reply_text.await_args.args[0]
        assert line in final and len(final) > len(line)
        entry = _entry_for_line("roast", line)
        assert entry.get("target") in (None, "السيسي"), final
        seen_targets.add(entry.get("target"))
    assert len(router.calls) == 30
    assert grounding_calls == []
    assert "السيسي" in seen_targets


async def test_opinion_stance_end_to_end(
        memory_fakes, settings, tmp_db, monkeypatch):
    # "ايه رأيك في التعدد": just_chat + opinion — the LLM call must
    # carry the stance note, and the final reply must carry no banned
    # AI phrase and pass the voice check.
    grounding_calls = []
    _grounding_stub(monkeypatch, grounding_calls)
    stance = "التعدد ده حق الراجل، واللي مش عاجبه يخبط راسه في الحيط يا عم."
    router = ScriptedRouter([stance])
    ctx, bot, msg, user = await _run_turn(
        monkeypatch, settings, "يا بهجت " + LIVE_OPINION, router,
        update_id=920)
    assert grounding_calls == []
    assert len(router.calls) == 1
    assert any(m.get("content") == h._OPINION_NOTE
               for m in router.calls[0]), "stance note missing from LLM call"
    final = msg.reply_text.await_args.args[0]
    assert final == stance
    assert not any(b in final for b in BANNED)
    assert check_reply(final, "full", OWNER_ID)[0] is True
    assert voice_check(final, mood=30) == []


async def test_identity_denial_end_to_end(
        memory_fakes, settings, tmp_db, monkeypatch):
    # v1.8: "يا بهجت انت بوت؟" — the LLM call must carry the identity
    # rule in the system prompt, and a proper denial goes out unchanged.
    grounding_calls = []
    _grounding_stub(monkeypatch, grounding_calls)
    denial = "لأ يا عم، أنا بهجت، إنسان عادي، مش بوت."
    router = ScriptedRouter([denial])
    ctx, bot, msg, user = await _run_turn(
        monkeypatch, settings, "يا بهجت " + LIVE_ARE_YOU_BOT, router,
        update_id=950)
    assert grounding_calls == []
    assert len(router.calls) == 1
    assert any("إنسان عادي" in (m.get("content") or "")
               and "مش بوت" in (m.get("content") or "")
               for m in router.calls[0]), "identity rule missing from LLM call"
    final = msg.reply_text.await_args.args[0]
    assert final == denial
    assert check_reply(final, "full", OWNER_ID)[0] is True
    assert voice_check(final, mood=30) == []


async def test_identity_admission_is_rewritten(
        memory_fakes, settings, tmp_db, monkeypatch):
    # v1.8: even if the LLM says it is a bot, what goes out must be an
    # in-character denial — the bot never admits it (voice check flags
    # the draft, the regen still admits, check_reply replaces it).
    grounding_calls = []
    _grounding_stub(monkeypatch, grounding_calls)
    admission = "أنا بوت ذكاء اصطناعي، آسف يا عم."
    router = ScriptedRouter([admission, admission])
    ctx, bot, msg, user = await _run_turn(
        monkeypatch, settings, "يا بهجت " + LIVE_ARE_YOU_AI, router,
        update_id=951)
    assert len(router.calls) == 2  # first draft + one regeneration
    final = msg.reply_text.await_args.args[0]
    assert final == _SELF_BOT_DENIAL
    assert contains_self_bot_admission(final) is False
    assert check_reply(final, "full", OWNER_ID)[0] is True


async def test_joke_goes_out_as_voice(
        memory_fakes, settings, tmp_db, monkeypatch):
    # "بهجت قولي نكته": voice intent + bank joke line — sent as a voice
    # note, no LLM call, no text reply. (The "يا بهجت ..." form fires
    # the same prefix since v1.7 — see test_ya_joke_goes_out_as_voice.)
    grounding_calls = []
    _grounding_stub(monkeypatch, grounding_calls)
    send_voice = AsyncMock(return_value=True)
    monkeypatch.setattr(h, "_try_send_voice", send_voice)
    router = ScriptedRouter(["x"])
    ctx, bot, msg, user = await _run_turn(
        monkeypatch, settings, "بهجت " + LIVE_JOKE, router,
        update_id=930)
    assert router.calls == []
    assert grounding_calls == []
    send_voice.assert_awaited_once()
    joke = send_voice.await_args.args[3]
    assert joke in {e["line"] for e in load_bank()["joke_request"]}
    msg.reply_text.assert_not_awaited()


async def test_ya_joke_goes_out_as_voice(
        memory_fakes, settings, tmp_db, monkeypatch):
    # v1.7: "يا بهجت قولي نكته" — Seif's usual form — must reach the
    # voice prefix too: bank joke line as a voice note, no LLM call.
    grounding_calls = []
    _grounding_stub(monkeypatch, grounding_calls)
    send_voice = AsyncMock(return_value=True)
    monkeypatch.setattr(h, "_try_send_voice", send_voice)
    router = ScriptedRouter(["x"])
    ctx, bot, msg, user = await _run_turn(
        monkeypatch, settings, "يا بهجت " + LIVE_JOKE, router,
        update_id=933)
    assert router.calls == []
    assert grounding_calls == []
    send_voice.assert_awaited_once()
    joke = send_voice.await_args.args[3]
    assert joke in {e["line"] for e in load_bank()["joke_request"]}
    msg.reply_text.assert_not_awaited()


async def test_joke_voice_failure_is_visible(
        memory_fakes, settings, tmp_db, monkeypatch):
    # Voice synthesis failed: the text fallback must SAY the voice
    # didn't come out, not silently pretend it did.
    grounding_calls = []
    _grounding_stub(monkeypatch, grounding_calls)
    monkeypatch.setattr(h, "_try_send_voice", AsyncMock(return_value=False))
    router = ScriptedRouter(["x"])
    ctx, bot, msg, user = await _run_turn(
        monkeypatch, settings, "بهجت " + LIVE_JOKE, router,
        update_id=931)
    final = msg.reply_text.await_args.args[0]
    # v1.9: the voice-failure note is a random pick from the pool.
    assert any(line in final for line in h._VOICE_FAILURE_LINES)


async def test_youtube_song_offers_pick_list(
        memory_fakes, settings, tmp_db, monkeypatch):
    # "عايز اغنية مروان موسي الخلاصه": YouTube search -> pick list with
    # the three results as buttons, state stored for the tap.
    grounding_calls = []
    _grounding_stub(monkeypatch, grounding_calls)
    yt_calls = []
    _yt_stub(monkeypatch, yt_calls, n=3)
    router = ScriptedRouter(["x"])
    ctx, bot, msg, user = await _run_turn(
        monkeypatch, settings, "يا بهجت " + LIVE_SONG, router,
        update_id=940)
    assert grounding_calls == []  # YouTube, not web search
    assert yt_calls == ["مروان موسي الخلاصه"]
    assert router.calls == []
    list_text = _last_status_edit(bot)
    assert list_text is not None
    assert list_text.startswith("• نتائج البحث ← مروان موسي الخلاصه")
    for i in range(3):
        assert f"مروان موسي - الخلاصه {i}" in list_text
    kb = bot.sent_status[0].edit_text.await_args.kwargs["reply_markup"]
    assert [b.callback_data for row in kb.inline_keyboard for b in row] == \
        ["yt:pick:0", "yt:pick:1", "yt:pick:2"]
    state = ctx.application.bot_data["yt_requests"].get(
        (CHAT_ID, 77, 777))
    assert state is not None and len(state["results"]) == 3


async def test_youtube_bare_request_asks_for_a_name(
        memory_fakes, settings, tmp_db, monkeypatch):
    # Bare "عايز اغنية" has no title to search: the bot asks for a
    # name instead of searching the request words or crashing.
    grounding_calls = []
    _grounding_stub(monkeypatch, grounding_calls)
    yt_calls = []
    _yt_stub(monkeypatch, yt_calls, n=3)
    router = ScriptedRouter(["x"])
    ctx, bot, msg, user = await _run_turn(
        monkeypatch, settings, "يا بهجت عايز اغنية", router,
        update_id=941)
    assert yt_calls == []
    assert grounding_calls == []
    assert router.calls == []
    assert "جرب اسم تاني" in (_last_status_edit(bot) or "")


async def test_haat_prefix_youtube(
        memory_fakes, settings, tmp_db, monkeypatch):
    # "بهجت هات اغنية ..." prefix: the remainder is already the bare query.
    grounding_calls = []
    _grounding_stub(monkeypatch, grounding_calls)
    yt_calls = []
    _yt_stub(monkeypatch, yt_calls, n=3)
    router = ScriptedRouter(["x"])
    ctx, bot, msg, user = await _run_turn(
        monkeypatch, settings, "بهجت " + LIVE_HAAT, router,
        update_id=942)
    assert yt_calls == ["مروان موسي الخلاصه"]
    assert grounding_calls == []
    assert "مروان موسي - الخلاصه 0" in (_last_status_edit(bot) or "")


async def test_dawwar_search_mode(
        memory_fakes, settings, tmp_db, monkeypatch):
    # "بهجت دور حادثة الوراق": search mode — the grounding query is the
    # prefix remainder (normalised), the answer edits the status bubble.
    grounding_calls = []
    _grounding_stub(monkeypatch, grounding_calls)
    answer = "اللي حصل في الوراق إن فيه حادثة كبيرة يا عم."
    router = ScriptedRouter([answer])
    ctx, bot, msg, user = await _run_turn(
        monkeypatch, settings, "بهجت " + LIVE_SEARCH, router,
        update_id=950)
    assert grounding_calls == ["حادثه الوراق"]
    assert len(router.calls) == 1
    assert _last_status_edit(bot) == answer
    msg.reply_text.assert_not_awaited()


async def test_ya_dawwar_searches_clean_remainder(
        memory_fakes, settings, tmp_db, monkeypatch):
    # FIXED (v1.7): "يا بهجت دور حادثة الوراق" fires the prefix layer,
    # so the grounding query is the clean remainder ("حادثه الوراق"),
    # not the raw text with "يا بهجت" in it.
    grounding_calls = []
    _grounding_stub(monkeypatch, grounding_calls)
    answer = "اللي حصل في الوراق إن فيه حادثة كبيرة يا عم."
    router = ScriptedRouter([answer])
    ctx, bot, msg, user = await _run_turn(
        monkeypatch, settings, "يا بهجت " + LIVE_SEARCH, router,
        update_id=952)
    assert grounding_calls == ["حادثه الوراق"]
    assert len(router.calls) == 1
    assert _last_status_edit(bot) == answer


async def test_qawl_voice_mode(
        memory_fakes, settings, tmp_db, monkeypatch):
    # "بهجت قول اهلا في فويس نوت": voice mode — the LLM reply goes out
    # as a voice note INSTEAD of text, and no search runs for it.
    grounding_calls = []
    _grounding_stub(monkeypatch, grounding_calls)
    send_voice = AsyncMock(return_value=True)
    monkeypatch.setattr(h, "_try_send_voice", send_voice)
    spoken = "اهلا يا عم، عامل ايه؟"
    router = ScriptedRouter([spoken])
    ctx, bot, msg, user = await _run_turn(
        monkeypatch, settings, "بهجت " + LIVE_VOICE, router,
        update_id=951)
    assert grounding_calls == []
    assert len(router.calls) == 1
    send_voice.assert_awaited_once()
    assert send_voice.await_args.args[3] == spoken
    msg.reply_text.assert_not_awaited()


async def test_followup_inherits_topic_at_handler_level(
        memory_fakes, settings, tmp_db, monkeypatch):
    # "يا بهجت ايه الحصل" after the Waraq turn: the search query must
    # carry the Waraq topic from history, not search the bare phrase
    # (the old bug grounded the answer on song lyrics).
    grounding_calls = []
    _grounding_stub(monkeypatch, grounding_calls)
    monkeypatch.setattr(
        h, "recent_messages",
        lambda chat_id, limit=8: [
            {"role": "user", "content": WARAK_TURN, "user_id": 777,
             "first_name": "Seif Allah Mo"}])
    router = ScriptedRouter(["اللي حصل في الوراق كذا وكذا يا عم."])
    ctx, bot, msg, user = await _run_turn(
        monkeypatch, settings, "يا بهجت " + LIVE_FOLLOWUP, router,
        update_id=960)
    assert len(grounding_calls) == 1
    assert "الوراق" in grounding_calls[0]
    assert grounding_calls[0] != LIVE_FOLLOWUP
    assert _last_status_edit(bot) == "اللي حصل في الوراق كذا وكذا يا عم."


async def test_dawwar_min_handler_never_searches(
        memory_fakes, settings, tmp_db, monkeypatch):
    # "يا بهجت دور مين؟" at handler level: no grounding call, one LLM
    # call, a normal text reply — never a search.
    grounding_calls = []
    _grounding_stub(monkeypatch, grounding_calls)
    router = ScriptedRouter(["دورك يا عم، العب."])
    ctx, bot, msg, user = await _run_turn(
        monkeypatch, settings, "يا بهجت دور مين؟", router,
        update_id=970)
    assert grounding_calls == []
    assert len(router.calls) == 1
    assert msg.reply_text.await_args.args[0] == "دورك يا عم، العب."
