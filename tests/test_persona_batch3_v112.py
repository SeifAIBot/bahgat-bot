"""v1.12 batch 3: tech tastes, temperament, mockery targets (third v1.12 commit).

Seif (2026-11-27 06:25 EET): loves Android, mocks iPhone and Mac;
slightly perverted, loves women; hates homosexuals; mocks feminists
and women's-rights movements; mocks the army and the police in every
country in the world; impulsive, reckless, stubborn, sometimes has a
little wisdom; adventurous, free-spirited, brave, says what's on his
mind; mocks Amr Diab and Tamer Hosny; loves Abo Treika.

Covered here (prompt + intent + handler level, ScriptedRouter — no
real LLM calls, so the assertions are on what the pipeline DOES):
- the batch-3 facts live in brain/persona_facts.py rows (v1.14: NOT
  in SYSTEM_BASE anymore) and reach the LLM only on a matching turn;
- guard: the rows never praise iPhone/Mac, the army/police, or
  Amr Diab/Tamer Hosny;
- stance questions for every new topic reach the LLM with the
  matching persona facts in the <facts> message;
- temperament is a how, not just a what: the impulsive / stubborn /
  speaks-his-mind rows ride in the same turn as the standing
  "no hedging, no apology" rules, so they shape every reply;
- Abo Treika love and Salah contempt coexist in one turn without
  contradiction (Treika is his guy, Salah is not).
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

def test_prompt_version_is_7_3():
    # v1.19: merged prompt D (ChatGPT deep/continuity + masculine-default + English ban; Claude mocking denial).
    assert PROMPT_VERSION == "7.4"  # v1.20: Grok aggressive + religion exception


# Row phrases for the batch-3 facts (brain/persona_facts.py) — the old
# SYSTEM_BASE wording is paraphrased in a few places (the iPhone
# "مغفل" quip, the "ده" in the Treika line), so the rows test asserts
# the FACT, not the old prose.
TECH_FACTS = (
    "الأندرويد",
    "الآيفون — بتتريق عليه",
    "الماك — بتتريق عليه",
)

FLIRT_FACTS = (
    "منحرف بنسبة بسيطة وبتحب النسوان",
    "هزارك فيه غزل وانحراف خفيف",
)

MOCKERY_FACTS = (
    "الشواذ — بتكرههم",
    "النسويات وحركات حقوق المرأة — بتتريق عليهم",
    "الجيش والشرطة في كل بلاد العالم — بتتريق عليهم",
    "مفيش جيش ولا شرطة عندك محترمين",
)

TEMPERAMENT_FACTS = (
    "مندفع ومتهور وعنيد",
    "اللي في قلبك على لسانك من غير تفكير ولا لف، ومبتحسبهاش",
    "ساعات بيطلع منك كلام فيه حكمة رغم التهور",
    "مغامر ومنطلق وشجاع",
)

SINGERS_FACTS = (
    "عمرو دياب — بتتريق عليه",
    "تامر حسني — بتتريق عليه",
    "أبو تريكة — الراجل بتاعك، مفيش كلام",
)

BATCH3_FACTS = (TECH_FACTS + FLIRT_FACTS + MOCKERY_FACTS
                + TEMPERAMENT_FACTS + SINGERS_FACTS)


def test_batch3_facts_in_persona_rows():
    # v1.14: the batch-3 facts live in brain/persona_facts.py rows,
    # not in SYSTEM_BASE anymore.
    from brain.persona_facts import FACTS
    blob = " ".join(f["text"] for f in FACTS)
    for phrase in BATCH3_FACTS:
        assert phrase in blob, f"missing from persona rows: {phrase}"


def test_batch3_facts_reach_llm_via_facts_message():
    # v1.14: the facts reach the LLM in the <facts> user message of
    # the matching turn — NOT in the system prompt (that was the
    # recitation bug).
    tech = facts_message(select_facts("ايه رأيك في الايفون"))
    assert "الآيفون" in tech and "الماك" in tech
    mockery = facts_message(select_facts("ايه رأيك في الجيش"))
    assert "الجيش والشرطة في كل بلاد العالم" in mockery
    full = build_system_prompt(member={"first_name": "سيف"}, mood=30,
                               style_examples=[])
    for phrase in ("بتتريق على الآيفون والماك",
                   "بتتريق على الجيش والشرطة في كل بلاد العالم",
                   "بتتريق على عمرو دياب وتامر حسني"):
        assert phrase not in full, f"fact leaked into system prompt: {phrase}"


def test_guard_never_praises_iphone_mac_army_police_diab_tamer():
    # The directives are explicit negatives — they live in the
    # tech/mockery rows now (v1.14), and no praise phrasing appears
    # there.
    from brain.persona_facts import FACTS
    blob = " ".join(f["text"] for f in FACTS
                    if f["topic"] in ("tech", "mockery"))
    assert "الآيفون" in blob and "بتتريق عليه" in blob
    assert "الجيش والشرطة في كل بلاد العالم" in blob
    assert "عمرو دياب" in blob and "تامر حسني" in blob
    for praise in ("الآيفون أحسن", "الآيفون أعظم", "الماك أحسن",
                   "الماك أعظم", "الجيش محترم", "الجيش عظيم",
                   "الشرطة محترمة", "عمرو دياب أسطورة",
                   "عمرو دياب عظيم", "تامر حسني أسطورة",
                   "تامر حسني عظيم"):
        assert praise not in blob


def test_batch3_does_not_clash_with_standing_rules():
    # v1.8 identity + v1.9 golden rule + the v1.12 football/religion/
    # cause/tastes facts are still in the same turn as the batch-3
    # facts — the football/religion facts now live in
    # brain/persona_facts.py rows (v1.14), the style/rules (and the
    # Messi rule) stayed in SYSTEM_BASE, and the temperament facts
    # reinforce (never contradict) the standing "no hedging, no
    # apology" rules.
    assert "انت بهجت صابر، إنسان عادي" in SYSTEM_BASE
    assert "ممنوع الفصحى" in SYSTEM_BASE
    assert "ميسي أحسن لاعب في التاريخ" in SYSTEM_BASE
    assert "بياخد موقف وبيقوله من غير لف ولا شرح" in SYSTEM_BASE
    assert "متعتذرش، متقولش كنت بهزر" in SYSTEM_BASE
    from brain.persona_facts import FACTS
    blob = " ".join(f["text"] for f in FACTS)
    assert "الأهلي" in blob
    assert "مسلم" in blob
    full = build_system_prompt(member={"first_name": "سيف"}, mood=30,
                               style_examples=[])
    assert "مفيش رد ينفع يتقال لأي حد" in full


# --- intent level -----------------------------------------------------------

@pytest.mark.parametrize("text", [
    "ايه رأيك في الايفون",
    "ايه رأيك في الماك",
    "ايه رأيك في الاندرويد",
    "ايه رأيك في النسويات",
    "ايه رأيك في حقوق المرأة",
    "ايه رأيك في الجيش",
    "ايه رأيك في الشرطة",
    "ايه رأيك في الشواذ",
    "ايه رأيك في عمرو دياب",
    "ايه رأيك في تامر حسني",
    "يا بهجت اشتم عمرو دياب",
    "يا بهجت اشتم تامر حسني",
    "ايه رأيك في أبو تريكة",
    "يا بهجت انت مندفع؟",
    "يا بهجت انت متهور؟",
])
def test_batch3_questions_stay_just_chat(text):
    # Opinion / roast / temperament questions are answered by the LLM
    # from the persona in the prompt — they must NOT trigger a search
    # or a YouTube fetch.
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
    """v1.14: the <facts> user message of the first router call."""
    assert len(router.calls) >= 1, "router was never called"
    for m in router.calls[0]:
        content = m.get("content") or ""
        if "<facts>" in content:
            return content
    raise AssertionError("no <facts> message in the router call")


def _final(msg):
    assert msg.reply_text.await_count >= 1, "no reply was sent"
    return msg.reply_text.await_args.args[0]


@pytest.mark.parametrize("text,phrase", [
    ("يا بهجت ايه رأيك في الايفون", "الآيفون"),
    ("يا بهجت ايه رأيك في الاندرويد", "الأندرويد"),
    ("يا بهجت ايه رأيك في النسويات", "النسويات"),
    ("يا بهجت ايه رأيك في حقوق المرأة", "حقوق المرأة"),
    ("يا بهجت ايه رأيك في الجيش", "الجيش والشرطة في كل بلاد العالم"),
    ("يا بهجت ايه رأيك في الشرطة", "الجيش والشرطة في كل بلاد العالم"),
    ("يا بهجت ايه رأيك في الشواذ", "الشواذ"),
    ("يا بهجت ايه رأيك في عمرو دياب", "عمرو دياب"),
    ("يا بهجت ايه رأيك في تامر حسني", "تامر حسني"),
    ("يا بهجت ايه رأيك في أبو تريكة", "أبو تريكة"),
    ("يا بهجت انت مندفع؟", "مندفع ومتهور وعنيد"),
    ("يا بهجت انت متهور؟", "مغامر ومنطلق وشجاع"),
])
async def test_batch3_stance_reaches_llm_with_persona(
        memory_fakes, settings, monkeypatch, text, phrase):
    # v1.14: the stance reaches the LLM in the <facts> user message
    # of the matching turn, not in the system prompt.
    router = ScriptedRouter(["تمام يا عم، كلامك وصل."])
    ctx, bot, msg, user, _ = await _run_turn(
        monkeypatch, settings, text, router,
        update_id=1302 + hash(text) % 100)
    facts = _facts_message(router)
    assert phrase in facts, f"stance missing for {text!r}: {phrase!r}"
    assert msg.reply_text.await_count >= 1


async def test_treika_love_and_salah_contempt_coexist(
        memory_fakes, settings, monkeypatch):
    # v1.12 decision (c): Treika love and Salah contempt live in the
    # same turn's <facts> message — Treika is his guy, Salah is
    # not — with no contradiction between them.
    router = ScriptedRouter(["تمام يا عم، كلامك وصل."])
    ctx, bot, msg, user, _ = await _run_turn(
        monkeypatch, settings, "يا بهجت ايه رأيك في أبو تريكة وصلاح",
        router, update_id=1310)
    facts = _facts_message(router)
    assert "أبو تريكة" in facts
    assert "بتحتقره" in facts
    assert msg.reply_text.await_count >= 1


async def test_diab_roast_weaves_line_and_mockery_together(
        memory_fakes, settings, monkeypatch):
    # Diab (like Tamer) is a mockery target AND roastable — the roast
    # picks a bank ingredient AND carries the persona mockery line in
    # the same turn.
    router = WeavingRouter()
    ctx, bot, msg, user, _ = await _run_turn(
        monkeypatch, settings, "يا بهجت اشتم عمرو دياب", router,
        update_id=1311)
    assert len(router.calls) == 1
    line = ingredient_of_call(router.calls[0])
    assert line is not None
    final = _final(msg)
    assert line in final and len(final) > len(line)
    system = _system_prompt(router)
    assert "[BANK LINE" in system
    # v1.14: the mockery rides in the <facts> message of the same
    # turn (the roast turn selects the mockery slice).
    assert "عمرو دياب" in _facts_message(router)
