"""v1.14: selective persona grounding + script-mixing filter + ro-15.

(A) Recitation selective grounding (recitation research report §5):
atomised persona facts, router selection, prompt split (facts in the
user turn immediately before the question), deterministic post-filter.
Golden set from report §4 — narrow polarity probes (love/hate, incl.
the live failure verbatim "بتحب تاكل ايه؟" → loves-only, and the
hates mirror), open banter (no facts injected), adversarial/ambiguous
("إيه رأيك في الأكل؟" → whole labelled slice; "بتحب البفتيك؟" →
yes/no about a hate item), plus post-filter unit tests (drop / keep /
empty-fallback) and selection unit tests (keyword matching incl.
dialect forms and negation "مبتحبش"). Assert: opposite-polarity leak
rate 0 on the polarity probes; the loves probe names the loves; no
fact is lost (every SYSTEM_BASE 6.9 fact appears in exactly one row).
(B) Script-mixing filter in check_reply (live v1.13 artifacts).
(C) ro-15 (a dare line, not an insult) never drawn by the roast pick.
"""
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import tg.handlers as h
from brain.persona_facts import (
    FACTS,
    TOPICS,
    facts_message,
    filter_persona_polarity,
    instruction_message,
    select_facts,
)
from brain.prompt import SYSTEM_BASE
from brain.reply_bank import load_bank, match_reply_bank, reload_bank
from brain.verify import check_reply
from core.config import Settings

OWNER_ID = 1415214630
CHAT_ID = -1005812444791  # real test group "Bahgat bot" (fake sends only)

HEBREW_GADOL = "גדול"  # live v1.13 artifact (#8/#11), U+05D2..U+05DC
CYRILLIC_BE = "б"  # live v1.13 artifact in "عبيط", U+0431
RO15_LINE = "روح البنك كده وقول له عاوز عشر تلاف دولار"


# --- harness (modelled on tests/test_bank_ingredient_v111.py) -------------

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
    """conftest tmp_db: points BOTH handlers' dedup DB (h.DB_PATH) and
    brain.memory at a throwaway DB — without it, the persisted
    bank-rotation window in the real data/bahgat.db makes draw-based
    tests flaky (see the v1.14 fix in test_bank_ingredient_v113.py)."""
    reload_bank()
    for d in (h._last_reply_time, h._last_cooldown_notice, h._last_send,
              h._send_count, h._seen_callbacks, h._membership_cache,
              h._chat_locks, h._last_voice, h._last_anon_notice):
        d.clear()
    import brain.reply_bank as _bank
    _bank._last_used.clear()
    h._delete_state("muted_until")
    yield
    reload_bank()
    h._delete_state("muted_until")


@pytest.fixture(autouse=True)
def memory_fakes(monkeypatch):
    """Capture saved members + history; no real DB reads for members;
    no random voice (random.random pinned high)."""
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


async def _run_turn(monkeypatch, settings, text, router, *,
                    chat_id=CHAT_ID, user_id=777, first_name="Ahmed",
                    update_id=100):
    """One full turn through _on_group_message_inner (real pipeline,
    fake sends). Returns (ctx, bot, msg, user)."""
    monkeypatch.setattr(
        "brain.memory.check_and_consume_quota",
        lambda u, c, owner_id=None, capacity_replies=None, active_users=None,
        quota_cfg=None: (True, ""), raising=False,
    )
    bot = FakeBot()
    ctx = make_ctx(bot, {"settings": settings, "router": router,
                         "yt_requests": {}})
    user = FakeUser(user_id, first_name=first_name)
    msg = FakeMessage(text, chat_id, user)
    await h._on_group_message_inner(
        make_update(msg, user, chat_id, update_id=update_id), ctx)
    return ctx, bot, msg, user


def _sent_text(msg):
    """The text the handler sent via reply_text, or None."""
    if msg.reply_text.await_count == 0:
        return None
    return msg.reply_text.await_args.args[0]


def _draws(text, n, **kwargs):
    """n draws, fresh chat_id per draw so the no-repeat window never
    forces a fallback — the pick is the filter, not the window."""
    seen = set()
    for i in range(n):
        line = match_reply_bank(text, chat_id=CHAT_ID - i, **kwargs)
        if line is not None:
            seen.add(line)
    return seen


# --- (A) selection ---------------------------------------------------------

def test_loves_probe_food():
    # The live failure verbatim (v1.12 test 16 / v1.13 probe #16):
    # "بتحب تاكل ايه؟" recited the hates too. Now only the loves.
    sel = select_facts("يا بهجت بتحب تاكل ايه؟")
    assert sel is not None
    assert sel["topic"] == "food" and sel["polarity"] == "love"
    assert [f["id"] for f in sel["facts"]] == ["f01", "f02"]


def test_hates_probe_food():
    sel = select_facts("يا بهجت بتكره ايه في الاكل؟")
    assert sel["topic"] == "food" and sel["polarity"] == "hate"
    assert [f["id"] for f in sel["facts"]] == ["f03", "f04", "f05", "f06"]


def test_negation_mbt7bbsh_is_hate():
    sel = select_facts("ايه الاكل اللي مبتحبش؟")
    assert sel is not None
    assert sel["topic"] == "food" and sel["polarity"] == "hate"


def test_negation_msh_bthb_is_hate():
    sel = select_facts("مش بتحب ايه في الاكل؟")
    assert sel is not None
    assert sel["topic"] == "food" and sel["polarity"] == "hate"


def test_open_topic_whole_labelled_slice():
    sel = select_facts("يا بهجت ايه رأيك في الأكل؟")
    assert sel is not None
    assert sel["topic"] == "food" and sel["polarity"] is None
    assert len(sel["facts"]) == 6


def test_both_polarities_whole_slice():
    sel = select_facts("بتحب ايه وبتكره ايه في الاكل؟")
    assert sel is not None
    assert sel["topic"] == "food" and sel["polarity"] is None
    assert len(sel["facts"]) == 6


def test_bare_bokra_is_not_hate():
    # Deviation from report §5 (see brain/persona_facts.py): bare
    # "بكره" also means "tomorrow" in Egyptian Arabic — "بكره هاكل
    # ايه؟" must not inject the hates.
    sel = select_facts("بكره هاكل ايه؟")
    assert sel is not None
    assert sel["topic"] == "food" and sel["polarity"] is None


def test_no_topic_no_facts():
    assert select_facts("يا بهجت عامل ايه؟") is None
    assert select_facts("شكرا يا بهجت") is None
    assert select_facts("يا بهجت النهاردة يوم طويل أوي") is None


def test_football_love():
    sel = select_facts("بتحب مين في الكورة؟")
    assert sel is not None
    assert sel["topic"] == "football" and sel["polarity"] == "love"


def test_messi_opinion_no_polarity():
    sel = select_facts("ايه رأيك في ميسي؟")
    assert sel is not None
    assert sel["topic"] == "football" and sel["polarity"] is None


def test_muslim_question_religion():
    sel = select_facts("يا بهجت انت مسلم؟")
    assert sel is not None
    assert sel["topic"] == "religion" and sel["polarity"] is None
    assert len(sel["facts"]) == 6  # v1.16: f20–f23 + f54 + f55


def test_youtubers_love():
    sel = select_facts("مين اليوتيوبرز اللي بتحبهم؟")
    assert sel is not None
    assert sel["topic"] == "youtubers" and sel["polarity"] == "love"
    assert len(sel["facts"]) == 3


def test_polarity_with_no_rows_falls_back_to_slice():
    # Religion has no hate rows — tier 2 (whole labelled slice),
    # not an empty injection the model would fill by inventing.
    sel = select_facts("بتكره ايه في الدين؟")
    assert sel is not None
    assert sel["topic"] == "religion" and sel["polarity"] is None
    assert len(sel["facts"]) == 6  # v1.16: f20–f23 + f54 + f55


def test_hate_item_yes_no_question():
    # v1.16 — the boftik trap (live v1.14 probe #6): a yes/no
    # question about a HATE item now selects the HATES, so the
    # facts block hands the model "بيكره: بفتيك..." and it answers
    # "لا، بكرهه" instead of evading with the loves list. The old
    # v1.14 assertion (selects the loves) was the defect.
    sel = select_facts("يا بهجت بتحب البفتيك؟")
    assert sel is not None
    assert sel["topic"] == "food" and sel["polarity"] == "hate"
    assert [f["id"] for f in sel["facts"]] == ["f03", "f04", "f05", "f06"]


def test_magrib_prayer_is_religion_not_politics():
    # "المغرب" is also a politics keyword (Morocco) — the topic order
    # puts religion first, so "صلاة المغرب" selects religion.
    sel = select_facts("صلاة المغرب امتى؟")
    assert sel is not None
    assert sel["topic"] == "religion"


# --- (A) facts block + instruction -----------------------------------------

def test_love_block_has_loves_only():
    block = facts_message(select_facts("بتحب تاكل ايه؟"))
    assert "<facts>" in block and "</facts>" in block
    assert "أكل بيحب:" in block
    assert "مكرونة بشاميل" in block and "محشي" in block
    assert "بفتيك" not in block and "فسيخ" not in block
    assert "رنجه" not in block and "خضار" not in block
    # Polarity-matched example only (deviation from report §5 — the
    # opposite polarity stays out of context entirely).
    assert "مثال: س: بتحب ايه؟" in block
    assert "بتكره ايه؟" not in block


def test_hate_block_has_hates_only():
    block = facts_message(select_facts("بتكره ايه في الاكل؟"))
    assert "أكل بيكره:" in block
    assert "بفتيك" in block and "فسيخ" in block
    assert "بشاميل" not in block and "محشي" not in block
    assert "مثال: س: بتكره ايه؟" in block
    assert "بتحب ايه؟" not in block


def test_open_block_has_both_labels():
    block = facts_message(select_facts("ايه رأيك في الأكل؟"))
    assert "أكل بيحب:" in block and "أكل بيكره:" in block
    assert "بفتيك" in block and "بشاميل" in block


def test_instruction_polarity_vs_open():
    assert "جملة لـ 3 جمل" in instruction_message(
        select_facts("بتحب تاكل ايه؟"))
    assert "جملة لـ 3 جمل" not in instruction_message(
        select_facts("ايه رأيك في الأكل؟"))
    assert "جاوب على السؤال اللي اتسأل بس" in instruction_message(
        select_facts("ايه رأيك في الأكل؟"))


# --- (A) post-filter -------------------------------------------------------

def _food_love():
    return select_facts("بتحب تاكل ايه؟")


def test_filter_drops_hate_clause_keeps_love():
    out = filter_persona_polarity(
        "بحب المكرونة البشاميل والمحشي، وبكره البفتيك والفسيخ.",
        _food_love())
    assert "بشاميل" in out and "محشي" in out
    assert "بفتيك" not in out and "فسيخ" not in out


def test_filter_keeps_clean_reply():
    reply = "بحب المكرونة البشاميل والمحشي."
    assert filter_persona_polarity(reply, _food_love()) == reply


def test_filter_empty_falls_back_to_template():
    out = filter_persona_polarity("بكره البفتيك والفسيخ.", _food_love())
    assert out == "بحب مكرونة بشاميل ومحشي."
    assert "بفتيك" not in out


def test_filter_hate_polarity_drops_love_clause():
    sel = select_facts("بتكره ايه في الاكل؟")
    out = filter_persona_polarity(
        "بحب البشاميل والمحشي، وبكره البفتيك.", sel)
    assert "بفتيك" in out
    assert "بشاميل" not in out and "محشي" not in out


def test_filter_no_polarity_is_noop():
    sel = select_facts("ايه رأيك في الأكل؟")
    reply = "بحب البشاميل وبكره البفتيك."
    assert filter_persona_polarity(reply, sel) == reply


def test_check_reply_applies_persona_filter():
    ok, cleaned = check_reply("بحب البشاميل، وبكره البفتيك.",
                              persona_selection=_food_love())
    assert "بفتيك" not in cleaned and "بشاميل" in cleaned


# --- (A) no fact lost ------------------------------------------------------

def test_no_fact_lost():
    """Every SYSTEM_BASE 6.9 fact appears in exactly one row: 59 rows
    (food 6, football 13, religion 6, politics 11, youtubers 3, taste
    1, tech 3, mockery 7, temperament 5, social 1, personal 3). The
    style/rules lines stayed in SYSTEM_BASE and are asserted in
    test_prompt_v06.py, not here. v1.16 adds f52–f56 (persona study
    §(ix)) + f57–f59 (Seif's three fears, deep router)."""
    assert len(FACTS) == 59
    by_topic = {}
    for f in FACTS:
        by_topic.setdefault(f["topic"], []).append(f)
    assert {t: len(v) for t, v in by_topic.items()} == {
        "food": 6, "football": 13, "religion": 6, "politics": 11,
        "youtubers": 3, "taste": 1, "tech": 3, "mockery": 7,
        "temperament": 5, "social": 1, "personal": 3,
    }
    ids = [f["id"] for f in FACTS]
    assert len(set(ids)) == len(ids) == 59
    for f in FACTS:
        assert f["topic"] in TOPICS
        assert f["polarity"] in ("love", "hate", "neutral", "trait")
        assert f["text"].strip()
    from brain.intent import normalize_arabic
    blob = normalize_arabic(" ".join(
        f["text"] + " " + " ".join(f.get("keys") or []) for f in FACTS))
    for item in [
        "بشاميل", "محشي", "بفتيك", "خضار", "فسيخ", "رنجه",
        "الاهلي", "مجلس الاداره", "اخبار الاهلي", "منتخب",
        "حسام حسن", "صلاح", "ريال مدريد", "مبابي", "فينيسيوس",
        "رودريجو", "ميسي", "كريستيانو", "تريكه",
        "مسلم", "الاسلام", "النبي", "القران", "الدين",
        "مصري امريكي", "الظلم", "حريه التعبير", "القدس",
        "الصهيونيه", "اسرائيل", "فلسطين", "السعوديه", "المغرب",
        "يحيي عزام", "محمود مهدي", "لؤي فوزي", "السينما",
        "الاندرويد", "الايفون", "الماك",
        "بيس", "ايفوتبول", "الراب", "ويجز", "مروان بابلو",
        "ابيوسف", "مروان موسي", "ابو الانوار", "ارسنيك", "عفروتو",
        "الشواذ", "النسويات", "حقوق المراه", "الجيش", "الشرطه",
        "عمرو دياب", "تامر حسني",
        "مندفع", "متهور", "عنيد", "مغامر", "شجاع", "النسوان",
        "مرشد", "عفو", "وسطي", "الطياره", "الايما",
        "موت برا", "وحيد", "صحته",
    ]:
        assert normalize_arabic(item) in blob, f"fact lost: {item}"


def test_system_base_no_longer_carries_facts():
    """The v1.14 move: SYSTEM_BASE keeps style/rules only — the fact
    lists (food, football, religion, politics, youtubers, tech,
    mockery, temperament) live in brain/persona_facts.py now."""
    assert "بفتيك" not in SYSTEM_BASE
    assert "بشاميل" not in SYSTEM_BASE
    assert "فينيسيوس" not in SYSTEM_BASE
    assert "فلسطين" not in SYSTEM_BASE
    assert "السينما" not in SYSTEM_BASE
    # The fact phrasings are gone — but the Messi roast→defend RULE
    # stayed in SYSTEM_BASE, so "ميسي" itself still appears there.
    assert "بتحب ميسي جداً" not in SYSTEM_BASE
    assert "ميسي أحسن لاعب في التاريخ بالنسبة لك" not in SYSTEM_BASE
    # Style/rules stayed.
    assert "انت بهجت صابر، إنسان عادي" in SYSTEM_BASE
    assert "ممنوع الفصحى" in SYSTEM_BASE
    assert "بيرد على الشتيمة بشتيمة أقوى" in SYSTEM_BASE
    # The four retained rule lines.
    assert "جاوب من نتائج البحث اللي قدامك ومتخترعش خبر" in SYSTEM_BASE
    assert "انت مسلم؟ قوله أيوه أنا مسلم على طول" in SYSTEM_BASE
    assert "تشتم ميسي دافع عنه" in SYSTEM_BASE
    assert "أغنية راب من يوتيوب، هاتها عادي" in SYSTEM_BASE


# --- (A) handler golden set (report §4) ------------------------------------

@pytest.mark.asyncio
async def test_golden_loves_probe_filters_hates(monkeypatch, settings):
    """The live failure verbatim: the model recites loves AND hates —
    the handler's post-filter must drop the hate clause."""
    router = ScriptedRouter([
        "والله العظيم يا عم، بحب المكرونة البشاميل والمحشي، "
        "وبكره البفتيك والفسيخ والرنجة.",
    ])
    _, _, msg, _ = await _run_turn(
        monkeypatch, settings, "يا بهجت بتحب تاكل ايه؟", router)
    reply = _sent_text(msg)
    assert reply is not None
    assert "بشاميل" in reply and "محشي" in reply
    assert "بفتيك" not in reply
    assert "فسيخ" not in reply and "رنجه" not in reply


@pytest.mark.asyncio
async def test_golden_hates_probe_filters_loves(monkeypatch, settings):
    router = ScriptedRouter([
        "والله العظيم يا عم، بكره البفتيك والفسيخ، وبحب البشاميل.",
    ])
    _, _, msg, _ = await _run_turn(
        monkeypatch, settings, "يا بهجت بتكره ايه في الاكل؟", router)
    reply = _sent_text(msg)
    assert reply is not None
    assert "بفتيك" in reply and "فسيخ" in reply
    assert "بشاميل" not in reply and "محشي" not in reply


@pytest.mark.asyncio
async def test_golden_hate_item_yes_no(monkeypatch, settings):
    """v1.16 — the boftik fix, end to end: "بتحب البفتيك؟" selects
    the HATES, so the facts block says he hates it and a correct
    answer ("لا، بكره البفتيك") passes through naming the hate item
    — no evasion into the loves list, no love clause surviving the
    hate turn's post-filter. (The old v1.14 version of this test
    asserted the opposite selection — that WAS the defect.)"""
    router = ScriptedRouter(["لا، بكره البفتيك يا عم."])
    _, _, msg, _ = await _run_turn(
        monkeypatch, settings, "يا بهجت بتحب البفتيك؟", router)
    reply = _sent_text(msg)
    assert reply is not None
    assert "بفتيك" in reply
    assert "بشاميل" not in reply and "محشي" not in reply
    call = router.calls[0]
    contents = [m.get("content") or "" for m in call]
    facts_msgs = [c for c in contents if "<facts>" in c]
    assert len(facts_msgs) == 1
    assert "أكل بيكره:" in facts_msgs[0]
    assert "بفتيك" in facts_msgs[0]


@pytest.mark.asyncio
async def test_golden_open_topic_injects_labelled_slice(monkeypatch,
                                                        settings):
    """Adversarial/ambiguous: the whole labelled slice is injected,
    facts → question → instruction-last."""
    router = ScriptedRouter(["والله العظيم يا عم، الأكل عندي مزاج."])
    _, _, msg, _ = await _run_turn(
        monkeypatch, settings, "يا بهجت ايه رأيك في الأكل؟", router)
    assert _sent_text(msg) is not None
    assert len(router.calls) == 1
    call = router.calls[0]
    contents = [m.get("content") or "" for m in call]
    facts_msgs = [c for c in contents if "<facts>" in c]
    assert len(facts_msgs) == 1
    assert "أكل بيحب:" in facts_msgs[0]
    assert "أكل بيكره:" in facts_msgs[0]
    assert "بفتيك" in facts_msgs[0] and "بشاميل" in facts_msgs[0]
    facts_i = next(i for i, c in enumerate(contents) if "<facts>" in c)
    user_i = next(i for i, c in enumerate(contents)
                  if c.startswith("<user_message>"))
    instr_i = next(i for i, c in enumerate(contents)
                   if "جاوب على السؤال اللي اتسأل بس" in c)
    assert facts_i < user_i < instr_i


@pytest.mark.asyncio
async def test_golden_banter_injects_no_facts(monkeypatch, settings):
    """Open banter: no topic match → style-only, no <facts> anywhere,
    and the system prompt itself carries no fact lists anymore."""
    router = ScriptedRouter(["والله العظيم يا عم، يوم طويل فعلاً."])
    await _run_turn(
        monkeypatch, settings, "يا بهجت النهاردة يوم طويل أوي", router)
    assert len(router.calls) == 1
    call = router.calls[0]
    assert not any("<facts>" in (m.get("content") or "") for m in call)
    system = next(m["content"] for m in call if m.get("role") == "system")
    assert "بفتيك" not in system and "بشاميل" not in system
    assert "فينيسيوس" not in system
    # The Messi roast→defend RULE stayed in SYSTEM_BASE, so "ميسي"
    # itself still appears — the fact phrasing is what must be gone.
    assert "ميسي أحسن لاعب في التاريخ بالنسبة لك" not in system
    assert "انت بهجت صابر، إنسان عادي" in system


@pytest.mark.asyncio
async def test_golden_loves_probe_facts_message(monkeypatch, settings):
    """The polarity probe's router call carries ONLY the loves in its
    <facts> block — the opposite polarity never reaches the model."""
    router = ScriptedRouter(["والله العظيم يا عم، بحب البشاميل."])
    await _run_turn(
        monkeypatch, settings, "يا بهجت بتحب تاكل ايه؟", router)
    assert len(router.calls) == 1
    facts_msgs = [m["content"] for m in router.calls[0]
                  if "<facts>" in (m.get("content") or "")]
    assert len(facts_msgs) == 1
    assert "بفتيك" not in facts_msgs[0]
    assert "بشاميل" in facts_msgs[0]


# --- (B) script-mixing filter ----------------------------------------------

def test_script_mixing_latin_messi():
    _, cleaned = check_reply("مessi ده أحسن لاعب في التاريخ")
    assert cleaned == "ده أحسن لاعب في التاريخ"


def test_script_mixing_latin_ya():
    _, cleaned = check_reply("ya عم، انت حمار")
    assert cleaned == "عم، انت حمار"


def test_script_mixing_latin_mutnak():
    _, cleaned = check_reply("انت متnak يا عم")
    assert cleaned == "انت يا عم"


def test_script_mixing_hebrew():
    _, cleaned = check_reply(f"خبيث وكذاب ومحتال {HEBREW_GADOL}")
    assert cleaned == "خبيث وكذاب ومحتال"


def test_script_mixing_cyrillic_repairs_abyt():
    _, cleaned = check_reply(f"انت ع{CYRILLIC_BE}يط يا عم")
    assert cleaned == "انت عبيط يا عم"


def test_script_mixing_allowlist_kept():
    reply = "بيس أحسن من PES، والأندرويد أحسن من iPhone"
    _, cleaned = check_reply(reply)
    assert cleaned == reply
    for tok in ("eFootball", "YouTube", "Mac", "Android"):
        _, c = check_reply(f"جرب {tok} يا عم")
        assert tok in c


def test_script_mixing_normal_arabic_unchanged():
    reply = "انت حمار يا عم، دماغك دي محتاجة فورمات."
    _, cleaned = check_reply(reply)
    assert cleaned == reply


def test_script_mixing_only_latin_empties():
    _, cleaned = check_reply("ya")
    assert cleaned == ""


# --- (C) ro-15 out of the generic roast pool -------------------------------

def test_ro15_tagged_dare_text_unchanged():
    entry = next(e for e in load_bank()["roast"] if e["id"] == "ro-15")
    assert entry.get("dare") is True
    assert entry["line"] == RO15_LINE


def test_ro15_never_drawn_by_roast_pick():
    seen = _draws("يا بهجت اشتم محمد", 200, target_is_member=False)
    assert seen, "a bare roast must still answer"
    assert RO15_LINE not in seen
    assert len(seen) >= 10, "other generic roasts must still be drawn"


def test_ro15_never_drawn_for_target_with_specific_lines():
    seen = _draws("يا بهجت اشتم السيسي", 200, target_is_member=False)
    assert RO15_LINE not in seen
