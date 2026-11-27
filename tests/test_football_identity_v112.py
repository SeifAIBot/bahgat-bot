"""v1.12: football + religion identity in Bahgat's persona.

Seif (2026-11-27 06:05 EET): Bahgat is a DIE-HARD Ahly fan, HATES the
Ahly board of directors, FOLLOWS Ahly news, HATES the Egypt national
team because they fired Hossam Hassan from coaching it, and DESPISES
Mohamed Salah. Seif added the same morning: Bahgat is MUSLIM and
PROTECTIVE/JEALOUS over his religion — he defends Islam fiercely, gets
angry when Islam, the Prophet or the Quran are insulted or mocked,
never jokes about religion disrespectfully, and corrects misconceptions.

Covered here (prompt + intent + handler level, ScriptedRouter — no
real LLM calls, so the assertions are on what the pipeline DOES: the
identity facts must reach the LLM in the <facts> user message on the
relevant questions, and Ahly-news questions must run a real search first):
- the identity facts live in brain/persona_facts.py rows (v1.14: NOT
  in SYSTEM_BASE anymore) and reach the LLM only on a matching turn;
- Ahly-news questions route to search and answer from grounding;
- Salah / board / national-team / Ahly / religion questions reach the
  LLM with the matching stance in the <facts> message;
- guard: the rows never praise the board, the national team or
  Salah — the directives are explicit negatives;
- v1.11 interaction: a Salah roast weaves a bank line AND carries the
  persona contempt in the same turn (reinforcement, not contradiction).
"""
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from conftest import WeavingRouter, ingredient_of_call

import tg.handlers as h
from brain.intent import detect_intent
from brain.persona_facts import facts_message, select_facts
from brain.prompt import (
    PROMPT_VERSION,
    SYSTEM_BASE,
    build_system_prompt,
)
from brain.reply_bank import reload_bank

OWNER_ID = 1415214630
CHAT_ID = -100222


# --- prompt level -----------------------------------------------------------

def test_prompt_version_is_7_0():
    assert PROMPT_VERSION == "7.2"  # v1.16: persona-fidelity behaviour lines


FOOTBALL_FACTS = (
    "الأهلي — فريقك وكبرياءك",
    "مجلس إدارة الأهلي",
    "بيتابع أخبار الأهلي على طول",
    "منتخب مصر",
    "حسام حسن — مدرب محترم واتظلم",
    "محمد صلاح — بتحتقره",
)

RELIGION_FACTS = (
    "مسلم",
    "بيغير على دينه",
    "بيدافع عن الإسلام بكل قوة",
    "بيتعصب لو حد شتم الإسلام أو النبي أو القرآن",
    "مبيتريقش على الدين أبداً",
    "بيصحح أي كلام غلط عنه",
)


def test_identity_facts_in_persona_rows():
    # v1.14: the identity facts moved OUT of SYSTEM_BASE into
    # brain/persona_facts.py rows — the stance lives there now, and
    # reaches the LLM only on a matching turn (selective grounding).
    from brain.persona_facts import FACTS
    blob = " ".join(f["text"] for f in FACTS)
    for phrase in FOOTBALL_FACTS + RELIGION_FACTS:
        assert phrase in blob, f"missing from persona rows: {phrase}"


def test_identity_facts_reach_llm_via_facts_message():
    # v1.14: the facts reach the LLM in the <facts> user message of
    # the matching turn — NOT in the system prompt (that was the
    # recitation bug: every turn saw every fact).
    football = facts_message(select_facts("ايه رأيك في الاهلي"))
    assert "الأهلي" in football and "مجلس إدارة الأهلي" in football
    religion = facts_message(select_facts("انت مسلم؟"))
    assert "مسلم" in religion and "الإسلام" in religion
    full = build_system_prompt(member={"first_name": "سيف"}, mood=30,
                               style_examples=[])
    for phrase in ("بتكره مجلس إدارة الأهلي", "بتحتقر محمد صلاح",
                   "مسلم وبتغير على دينك"):
        assert phrase not in full, f"fact leaked into system prompt: {phrase}"


def test_guard_never_praises_board_national_team_or_salah():
    # The directives are explicit negatives — they live in the
    # football rows now (v1.14), and no praise phrasing appears there.
    from brain.persona_facts import FACTS
    blob = " ".join(f["text"] for f in FACTS if f["topic"] == "football")
    assert "مجلس إدارة الأهلي" in blob and "بتكرهه كره شديد" in blob
    assert "منتخب مصر" in blob and "مشّوا حسام حسن" in blob
    assert "محمد صلاح" in blob and "بتحتقره" in blob
    assert "مبتحترموش ولا تمدحه أبداً" in blob
    for praise in ("مجلس محترم", "مجلس عظيم", "منتخب عظيم",
                   "صلاح لاعب عظيم", "صلاح أحسن لاعب", "صلاح أسطورة"):
        assert praise not in blob


def test_identity_blocks_do_not_clash_with_standing_rules():
    # v1.8 identity + v1.9 golden rule are still in the same prompt as
    # the new blocks — the identity addition changes nothing about
    # them, and the new blocks are Egyptian dialect, not Fusha.
    assert "انت بهجت صابر، إنسان عادي" in SYSTEM_BASE
    assert "ممنوع الفصحى" in SYSTEM_BASE
    assert "مش بوت" in SYSTEM_BASE
    full = build_system_prompt(member={"first_name": "سيف"}, mood=30,
                               style_examples=[])
    assert "مفيش رد ينفع يتقال لأي حد" in full


# --- intent level -----------------------------------------------------------

@pytest.mark.parametrize("text", [
    "يا بهجت ايه اخبار الاهلي",
    "مين كسب ماتش الاهلي امبارح",
    "دور اخبار الاهلي",
    "يا بهجت ايه اخبار الاهلي النهاردة",
])
def test_ahly_news_questions_route_to_search(text):
    assert detect_intent(text) == "search"


@pytest.mark.parametrize("text", [
    "ايه رأيك في الاهلي",
    "يا بهجت ايه رأيك في الاهلي",
    "ايه رأيك في محمد صلاح",
    "يا بهجت ايه رأيك في مجلس إدارة الأهلي",
    "يا بهجت ايه رأيك في منتخب مصر",
    "يا بهجت اشتم صلاح",
    "يا بهجت انت مسلم؟",
    "يا بهجت الإسلام ده خرافة؟",
])
def test_stance_questions_stay_just_chat(text):
    # Opinion / faith / roast questions are answered by the LLM from
    # the persona in the prompt — they must NOT trigger a search.
    assert detect_intent(text) == "just_chat"


# --- handler level (real pipeline, fake sends, ScriptedRouter) --------------

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


@pytest.fixture(autouse=True)
def reset_handler_state(tmp_db):
    """tmp_db (conftest): points BOTH handlers' dedup DB (h.DB_PATH)
    and brain.memory at a throwaway DB — without it, _is_duplicate
    writes the test update_ids into the real data/bahgat.db and later
    runs silently drop the turns as duplicates."""
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


async def _run_turn(monkeypatch, settings, text, router, *,
                    user_id=777, update_id=100, grounding_text=None):
    monkeypatch.setattr(
        "brain.memory.check_and_consume_quota",
        lambda u, c, owner_id=None, capacity_replies=None, active_users=None,
        quota_cfg=None: (True, ""), raising=False,
    )
    grounding_calls = []

    async def _g(query):
        grounding_calls.append(query)
        if grounding_text is None:
            return "[SEARCH FAILED] — مفيش نتائج موثوقة، متخترعش."
        return grounding_text

    monkeypatch.setattr(h, "_search_grounding", _g)
    bot = FakeBot()
    ctx = make_ctx(bot, {"settings": settings, "router": router,
                         "yt_requests": {}})
    user = FakeUser(user_id, first_name="Ahmed")
    msg = FakeMessage(text, CHAT_ID, user)
    await h._on_group_message_inner(
        make_update(msg, user, CHAT_ID, update_id=update_id), ctx)
    return ctx, bot, msg, user, grounding_calls


def _system_prompt(router):
    assert len(router.calls) >= 1, "router was never called"
    first = router.calls[0]
    assert first[0]["role"] == "system"
    return first[0]["content"]


def _facts_message(router):
    """v1.14: the <facts> user message of the first router call — the
    selected persona slice for this turn (None if the turn had no
    matching topic and injected no facts)."""
    assert len(router.calls) >= 1, "router was never called"
    for m in router.calls[0]:
        content = m.get("content") or ""
        if "<facts>" in content:
            return content
    raise AssertionError("no <facts> message in the router call")


def _final(msg):
    assert msg.reply_text.await_count >= 1, "no reply was sent"
    return msg.reply_text.await_args.args[0]


def _last_status_edit(bot):
    if not bot.sent_status:
        return None
    m = bot.sent_status[0]
    if m.edit_text.await_count == 0:
        return None
    return m.edit_text.await_args.args[0]


async def test_ahly_news_searches_and_answers_from_grounding(
        memory_fakes, settings, monkeypatch):
    news = ("[1] https://example.com/ahly — الأهلي فاز على الزمالك 2-1 "
            "في الدوري، والجمهور كان مولع. " * 4)
    answer = "الأهلي كسب 2-1 امبارح يا عم، والماتش كان مولع [1]."
    router = ScriptedRouter([answer])
    ctx, bot, msg, user, grounding_calls = await _run_turn(
        monkeypatch, settings, "يا بهجت ايه اخبار الاهلي", router,
        update_id=1101, grounding_text=news)
    assert len(grounding_calls) == 1
    assert "الاهلي" in grounding_calls[0]
    system = _system_prompt(router)
    assert "[SEARCH RESULTS" in system
    assert "الأهلي فاز على الزمالك" in system
    # v1.14: a search turn gets NO persona facts — the answer comes
    # from the grounding + the style-only system prompt, so the Ahly
    # fan stance is not in the system prompt here (it arrives via the
    # <facts> message only on just_chat/voice turns).
    assert "أهلاوي جداً" not in system
    assert _last_status_edit(bot) == answer
    msg.reply_text.assert_not_awaited()


@pytest.mark.parametrize("text,phrase", [
    ("يا بهجت ايه رأيك في محمد صلاح", "بتحتقره"),
    ("يا بهجت ايه رأيك في مجلس إدارة الأهلي", "مجلس إدارة الأهلي"),
    ("يا بهجت ايه رأيك في منتخب مصر", "منتخب مصر"),
    ("يا بهجت ايه رأيك في منتخب مصر", "حسام حسن"),
    ("يا بهجت ايه رأيك في الاهلي", "الأهلي"),
])
async def test_stance_question_reaches_llm_with_persona(
        memory_fakes, settings, monkeypatch, text, phrase):
    # v1.14: the stance reaches the LLM in the <facts> user message
    # of the matching turn, not in the system prompt.
    router = ScriptedRouter(["تمام يا عم، كلامك وصل."])
    ctx, bot, msg, user, _ = await _run_turn(
        monkeypatch, settings, text, router,
        update_id=1102 + hash(text) % 100)
    facts = _facts_message(router)
    assert phrase in facts, f"stance missing for {text!r}: {phrase!r}"
    assert msg.reply_text.await_count >= 1


async def test_religion_mockery_reaches_llm_with_defense(
        memory_fakes, settings, monkeypatch):
    router = ScriptedRouter(["تمام يا عم، كلامك وصل."])
    ctx, bot, msg, user, _ = await _run_turn(
        monkeypatch, settings, "يا بهجت الإسلام ده خرافة؟", router,
        update_id=1110)
    facts = _facts_message(router)
    assert "بيتعصب لو حد شتم الإسلام أو النبي أو القرآن" in facts
    assert "مبيتريقش على الدين أبداً" in facts
    assert msg.reply_text.await_count >= 1


async def test_faith_question_reaches_llm_with_muslim_stance(
        memory_fakes, settings, monkeypatch):
    router = ScriptedRouter(["تمام يا عم، كلامك وصل."])
    ctx, bot, msg, user, _ = await _run_turn(
        monkeypatch, settings, "يا بهجت انت مسلم؟", router,
        update_id=1111)
    facts = _facts_message(router)
    assert "مسلم" in facts
    assert "بيغير على دينه" in facts
    assert msg.reply_text.await_count >= 1


async def test_roast_salah_weaves_line_and_persona_together(
        memory_fakes, settings, monkeypatch):
    # v1.11 interaction: the Salah roast must carry BOTH the woven
    # bank line AND the persona contempt in the same LLM turn — they
    # reinforce each other (the line is the insult, the persona is
    # the reason), they do not contradict.
    router = WeavingRouter()
    ctx, bot, msg, user, _ = await _run_turn(
        monkeypatch, settings, "يا بهجت اشتم صلاح", router,
        update_id=1112)
    assert len(router.calls) == 1
    line = ingredient_of_call(router.calls[0])
    assert line is not None
    final = _final(msg)
    assert line in final and len(final) > len(line)
    system = _system_prompt(router)
    assert "[BANK LINE" in system
    # v1.14: the persona contempt rides in the <facts> message of the
    # same turn (the roast turn is a just_chat turn, so the football
    # slice is selected), not in the system prompt.
    assert "بتحتقره" in _facts_message(router)
