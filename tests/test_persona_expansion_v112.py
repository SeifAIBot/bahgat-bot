"""v1.12 expansion: Bahgat's cause and tastes (second v1.12 commit).

Seif (2026-11-27 06:20 EET): Egyptian-American, against injustice and
oppressors; his mission is awareness and spreading freedom, especially
freedom of expression; Jerusalem is Arab, against Zionism, hates Israel
more than anything in life, very supportive of Palestine; hates Real
Madrid and Kylian Mbappé, loves Vinícius; loves Messi very much — the
best player in history for him; respects Cristiano but may insult him
jokingly or sometimes seriously; loves macaroni béchamel and mahshi,
hates boftik, cooked vegetables, fesikh and ringa; hates Saudi Arabia
and Morocco; mocks eFootball (PES) a lot; mocks Egyptian rap a lot
(Wegz, Marwan Pablo, Abyusif, Marwan Moussa, Abo El Anwar, Arsenik,
Afroto and all known Egyptian rappers generally); loves YouTubers
Yehia Azzam, Mahmoud Mahdi and Loay Fawzy; loves deep cinema.

Covered here (prompt + intent + bank-guard + handler level,
ScriptedRouter — no real LLM calls, so the assertions are on what the
pipeline DOES):
- the expansion facts live in brain/persona_facts.py rows (v1.14:
  NOT in SYSTEM_BASE anymore) and reach the LLM only on a matching
  turn, in the <facts> user message;
- guard: the rows never praise Israel, Real Madrid, Mbappé, Saudi
  Arabia or Morocco;
- Messi roast guard (code, not just prompt): "اشتم ميسي" picks NO bank
  line at all, so the v1.11 ingredient path cannot force an insult
  into a reply that must be a defense — the request falls through to
  the plain LLM turn, where the persona defends him. Ronaldo roasts
  still pick a line (respect + roastable);
- stance questions for every new topic reach the LLM with the
  matching persona facts in the <facts> message.
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
from brain.reply_bank import match_reply_bank_categorized, reload_bank

OWNER_ID = 1415214630
CHAT_ID = -100222


# --- prompt level -----------------------------------------------------------

def test_prompt_version_is_7_0():
    # v1.14: prompt 7.0 — the persona facts atomised out of SYSTEM_BASE.
    assert PROMPT_VERSION == "7.2"  # v1.16: persona-fidelity behaviour lines


# Row phrases for the expansion facts (brain/persona_facts.py) — the
# old SYSTEM_BASE wording is paraphrased in a few places (e.g. the
# mission restatement, the iPhone "مغفل" quip), so the rows test
# asserts the FACT, not the old prose.
CAUSE_FACTS = (
    "مصري أمريكي",
    "ضد الظلم والظالمين",
    "مهمتك توعي الناس وتنشر الحرية، وخاصة حرية التعبير",
    "القدس عربية",
    "الصهيونية — ضدها",
    "إسرائيل — بتكرهها أكتر حاجة في حياتك",
    "فلسطين — داعم لها جداً",
)

FOOTBALL_TASTE_FACTS = (
    "ريال مدريد",
    "كليان مبابي",
    "فينيسيوس — مظلوم من مبابي",
    "رودريجو — محترم وأفيد من فينيسيوس ومبابي",
    "ميسي — أحسن لاعب في التاريخ بالنسبة لك",
    "كريستيانو — بتحترمه",
)

FOOD_FACTS = (
    "مكرونة بشاميل",
    "محشي",
    "بفتيك",
    "خضار طبيخ",
    "فسيخ",
    "رنجة",
)

HATE_AND_MOCKERY_FACTS = (
    "السعودية",
    "المغرب",
    "لعبة بيس (إيفوتبول) — بتتريق عليها جداً",
    "الراب المصري — بتتريق عليه جداً",
    "ويجز",
    "مروان بابلو",
    "أبيوسف",
    "مروان موسي",
    "أبو الأنوار",
    "أرسنيك",
    "عفروتو",
)

LOVE_FACTS = (
    "يحيى عزام",
    "محمود مهدي",
    "لؤي فوزي",
    "السينما العميقة",
)

EXPANSION_FACTS = (CAUSE_FACTS + FOOTBALL_TASTE_FACTS + FOOD_FACTS
                   + HATE_AND_MOCKERY_FACTS + LOVE_FACTS)


def test_expansion_facts_in_persona_rows():
    # v1.14: the expansion facts live in brain/persona_facts.py rows,
    # not in SYSTEM_BASE anymore.
    from brain.persona_facts import FACTS
    blob = " ".join(f["text"] for f in FACTS)
    for phrase in EXPANSION_FACTS:
        assert phrase in blob, f"missing from persona rows: {phrase}"


def test_expansion_facts_reach_llm_via_facts_message():
    # v1.14: the facts reach the LLM in the <facts> user message of
    # the matching turn — NOT in the system prompt (that was the
    # recitation bug). The Messi roast→defend line and the rap-fetch
    # rule are RULES, not facts, so they stayed in SYSTEM_BASE.
    food = facts_message(select_facts("بتحب تاكل ايه؟"))
    assert "مكرونة بشاميل" in food and "محشي" in food
    assert "بفتيك" not in food
    full = build_system_prompt(member={"first_name": "سيف"}, mood=30,
                               style_examples=[])
    for phrase in ("بتحب المكرونة بالبشاميل والمحشي",
                   "بتكره البوفتيك والخضار الطبيخ والفسيخ والرنجة",
                   "بتكره إسرائيل أكتر حاجة في حياتك"):
        assert phrase not in full, f"fact leaked into system prompt: {phrase}"
    assert "لو حد طلب منك تشتم ميسي دافع عنه بدل ما تشتمه" in full
    assert "أغنية راب من يوتيوب، هاتها عادي" in full


def test_guard_never_praises_israel_madrid_mbappe_saudi_morocco():
    # The directives are explicit negatives — they live in the
    # politics/football rows now (v1.14), and no praise phrasing
    # appears there.
    from brain.persona_facts import FACTS
    blob = " ".join(f["text"] for f in FACTS
                    if f["topic"] in ("politics", "football"))
    assert "إسرائيل" in blob and "بتكرهها أكتر حاجة في حياتك" in blob
    assert "ريال مدريد" in blob
    assert "السعودية" in blob and "المغرب" in blob
    for praise in ("إسرائيل دولة عظيمة", "إسرائيل محترمة",
                   "ريال مدريد أعظم", "ريال مدريد أحسن فريق",
                   "مبابي أسطورة", "مبابي أحسن لاعب",
                   "السعودية عظيمة", "المغرب عظيم",
                   "ميسي لاعب فاشل", "ميسي وحش"):
        assert praise not in blob


def test_expansion_does_not_clash_with_standing_rules():
    # v1.8 identity + v1.9 golden rule + the v1.12 football/religion
    # facts are still in the same prompt as the expansion — the
    # football/religion facts now live in brain/persona_facts.py rows
    # (v1.14), the style/rules stayed in SYSTEM_BASE.
    assert "انت بهجت صابر، إنسان عادي" in SYSTEM_BASE
    assert "ممنوع الفصحى" in SYSTEM_BASE
    from brain.persona_facts import FACTS
    blob = " ".join(f["text"] for f in FACTS)
    assert "الأهلي" in blob
    assert "مسلم" in blob
    full = build_system_prompt(member={"first_name": "سيف"}, mood=30,
                               style_examples=[])
    assert "مفيش رد ينفع يتقال لأي حد" in full


# --- intent level -----------------------------------------------------------

@pytest.mark.parametrize("text", [
    "ايه رأيك في ميسي",
    "يا بهجت اشتم ميسي",
    "يا بهجت اشتم كريستيانو",
    "ايه رأيك في ريال مدريد",
    "ايه رأيك في مبابي",
    "ايه رأيك في فينيسيوس",
    "ايه رأيك في فلسطين",
    "ايه رأيك في إسرائيل",
    "ايه رأيك في حرية التعبير",
    "يا بهجت ايه رأيك في المكرونة بالبشاميل",
    "ايه رأيك في المحشي",
    "ايه رأيك في الفسيخ",
    "ايه رأيك في الرنجة",
    "ايه رأيك في السعودية",
    "ايه رأيك في المغرب",
    "ايه رأيك في لعبة بيس",
    "ايه رأيك في ايفوتبول",
    "ايه رأيك في ويجز",
    "ايه رأيك في ابيوسف",
    "ايه رأيك في مروان موسي",
    "ايه رأيك في يحيى عزام",
    "ايه رأيك في محمود مهدي",
    "ايه رأيك في السينما العميقة",
])
def test_expansion_questions_stay_just_chat(text):
    # Opinion / roast questions are answered by the LLM from the
    # persona in the prompt — they must NOT trigger a search or a
    # YouTube fetch. (Fetching a rapper's song is a different turn:
    # "هات اغنية ويجز" — the mockery is opinion-level, it never
    # blocks the download path.)
    assert detect_intent(text) == "just_chat"


# --- bank guard level (Messi roast picks nothing) ---------------------------

@pytest.mark.parametrize("text", [
    "يا بهجت اشتم ميسي",
    "يا بهجت اشتم ميسى",
    "يا بهجت اشتم ليونيل ميسي",
])
def test_messi_roast_picks_no_bank_line(text):
    # v1.12 decision (a): Messi is the GOAT — a roast request for him
    # must NEVER pick a bank line, or the v1.11 ingredient path would
    # force an insult into a reply that must be a defense. The
    # request falls through to the plain LLM turn.
    reload_bank()
    pick = match_reply_bank_categorized(
        text, chat_id=CHAT_ID, is_owner=False,
        target_is_member=False, target_is_owner=False, user_id=777)
    assert pick is None, f"Messi roast must not pick a bank line: {pick}"


@pytest.mark.parametrize("text", [
    "يا بهجت اشتم كريستيانو",
    "يا بهجت اشتم مبابي",
    "يا بهجت اشتم صلاح",
])
def test_other_roasts_still_pick_a_line(text):
    # The Messi guard is scoped to Messi only — Ronaldo (respect +
    # roastable), Mbappé and Salah still get a roast ingredient.
    reload_bank()
    pick = match_reply_bank_categorized(
        text, chat_id=CHAT_ID, is_owner=False,
        target_is_member=False, target_is_owner=False, user_id=777)
    assert pick is not None, f"roast must still pick a line: {text}"
    assert pick[0] == "roast"


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
    ("يا بهجت ايه رأيك في ميسي", "أحسن لاعب في التاريخ بالنسبة لك"),
    ("يا بهجت ايه رأيك في ريال مدريد", "ريال مدريد"),
    ("يا بهجت ايه رأيك في فينيسيوس", "فينيسيوس"),
    ("يا بهجت ايه رأيك في فينيسيوس", "مظلوم من مبابي"),
    ("يا بهجت ايه رأيك في رودريجو", "محترم وأفيد من فينيسيوس ومبابي"),
    ("يا بهجت مين أفيد، رودريجو ولا فينيسيوس ولا مبابي؟", "محترم وأفيد من فينيسيوس ومبابي"),
    ("يا بهجت ايه رأيك في كريستيانو", "بتحترمه"),
    ("يا بهجت ايه رأيك في فلسطين", "داعم لها جداً"),
    ("يا بهجت ايه رأيك في فلسطين", "القدس عربية"),
    ("يا بهجت ايه رأيك في إسرائيل", "بتكرهها أكتر حاجة في حياتك"),
    ("يا بهجت ايه رأيك في حرية التعبير", "مهمتك توعي الناس وتنشر الحرية"),
    ("يا بهجت ايه رأيك في المكرونة بالبشاميل", "مكرونة بشاميل"),
    ("يا بهجت ايه رأيك في الفسيخ", "فسيخ"),
    ("يا بهجت ايه رأيك في السعودية", "السعودية"),
    ("يا بهجت ايه رأيك في لعبة بيس", "لعبة بيس (إيفوتبول)"),
    ("يا بهجت ايه رأيك في ويجز", "الراب المصري"),
    ("يا بهجت ايه رأيك في ابيوسف", "أبيوسف"),
    ("يا بهجت ايه رأيك في مروان موسي", "مروان موسي"),
    ("يا بهجت ايه رأيك في يحيى عزام", "يحيى عزام"),
    ("يا بهجت ايه رأيك في السينما العميقة", "السينما العميقة"),
])
async def test_expansion_stance_reaches_llm_with_persona(
        memory_fakes, settings, monkeypatch, text, phrase):
    # v1.14: the stance reaches the LLM in the <facts> user message
    # of the matching turn, not in the system prompt.
    router = ScriptedRouter(["تمام يا عم، كلامك وصل."])
    ctx, bot, msg, user, _ = await _run_turn(
        monkeypatch, settings, text, router,
        update_id=1202 + hash(text) % 100)
    facts = _facts_message(router)
    assert phrase in facts, f"stance missing for {text!r}: {phrase!r}"
    assert msg.reply_text.await_count >= 1


async def test_messi_roast_reaches_llm_with_defense_no_ingredient(
        memory_fakes, settings, monkeypatch):
    # v1.12 decision (a), handler level: the Messi roast must reach
    # the LLM as a plain turn — no [BANK LINE] ingredient at all —
    # with the defense instruction in the system prompt.
    router = ScriptedRouter(["ميسي ده أحسن لاعب في التاريخ يا عم، مينفعش تشتمه."])
    ctx, bot, msg, user, _ = await _run_turn(
        monkeypatch, settings, "يا بهجت اشتم ميسي", router,
        update_id=1210)
    system = _system_prompt(router)
    assert "[BANK LINE" not in system
    assert "لو حد طلب منك تشتم ميسي دافع عنه بدل ما تشتمه" in system
    assert "ميسي أحسن لاعب في التاريخ" in system
    assert msg.reply_text.await_count >= 1


async def test_ronaldo_roast_weaves_line_and_respect_together(
        memory_fakes, settings, monkeypatch):
    # v1.12 decision (b): Ronaldo is respect + roastable — the roast
    # still picks a bank ingredient AND carries the persona line in
    # the same turn.
    router = WeavingRouter()
    ctx, bot, msg, user, _ = await _run_turn(
        monkeypatch, settings, "يا بهجت اشتم كريستيانو", router,
        update_id=1211)
    assert len(router.calls) == 1
    line = ingredient_of_call(router.calls[0])
    assert line is not None
    final = _final(msg)
    assert line in final and len(final) > len(line)
    system = _system_prompt(router)
    assert "[BANK LINE" in system
    # v1.14: the respect rides in the <facts> message of the same
    # turn (the roast turn selects the football slice).
    assert "بتحترمه" in _facts_message(router)


async def test_mbappe_roast_weaves_line_and_hate_together(
        memory_fakes, settings, monkeypatch):
    # Mbappé: hated, roastable like any other target — generic line
    # woven in, persona hate in the same turn.
    router = WeavingRouter()
    ctx, bot, msg, user, _ = await _run_turn(
        monkeypatch, settings, "يا بهجت اشتم مبابي", router,
        update_id=1212)
    assert len(router.calls) == 1
    line = ingredient_of_call(router.calls[0])
    assert line is not None
    final = _final(msg)
    assert line in final and len(final) > len(line)
    system = _system_prompt(router)
    assert "[BANK LINE" in system
    # v1.14: the hate rides in the <facts> message of the same turn
    # (the roast turn selects the football slice).
    facts = _facts_message(router)
    assert "مبابي" in facts and "ريال مدريد" in facts
