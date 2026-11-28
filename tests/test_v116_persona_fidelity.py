"""v1.16 persona fidelity — the video-study delta + expert verdict.

Covers every new behaviour in the version:
- persona facts f52–f59 (study §(ix) + Seif's three fears), the new
  "social" topic, the boftik-trap flip in select_facts;
- the 17 new bank lines (ch-38/ch-39 dropped), the ro-37 fix,
  ro-47's family tag;
- prompt 7.2 (behavioural lines, deep variant, Style RAG sampler);
- the script-filter upgrades (U+FF0C, CJK), the garble dictionary,
  garble_flags, the sentence-loop dedupe;
- the deep router (fear containment on fear questions only);
- the roast-fallback vocative, the canned-deflection general
  detector, the search-misroute riff gate, the /diag handler order.
"""
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import tg.handlers as h
from brain.intent import looks_like_deep_question, looks_like_fear_question
from brain.persona_facts import (
    DEEP_FALLBACK_LINES,
    FACTS,
    deep_fallback_line,
    fear_facts,
    reply_names_fear,
    select_facts,
)
from brain.prompt import (
    PROMPT_VERSION,
    SYSTEM_BASE,
    build_system_prompt,
    deep_variant_block,
    sample_style_examples,
    style_rag_message,
)
from brain.reply_bank import (
    is_canned_deflection,
    load_bank,
    pick_dismiss_line,
    reload_bank,
    roast_fallback_reply,
    weave_about_target,
)
from brain.verify import check_reply, garble_flags
from core.persona import load_examples
from core.rules import contains_family_insult

OWNER_ID = 1415214630
CHAT_ID = -1005812444791
CANNED = "يا عم، الكلام ده مش داخل دماغي، قول حاجة عدلة."


# --- fakes (modelled on tests/test_v115_refusal_latency.py) -------------------

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


def make_ctx(bot, bot_data):
    return SimpleNamespace(bot=bot, application=SimpleNamespace(bot_data=bot_data))


def make_update(msg, user, chat_id, update_id=100):
    return SimpleNamespace(
        update_id=update_id, effective_message=msg, effective_user=user,
        effective_chat=FakeChat(chat_id), my_chat_member=None, callback_query=None,
    )


@pytest.fixture(autouse=True)
def reset_handler_state(tmp_db):
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
    return Settings(
        telegram_bot_token="x", gemini_api_key="g", groq_api_key="q",
        nvidia_api_key="n", owner_id=OWNER_ID, yt_cookies_path="",
        drop_pending_updates=True, allowed_chat_ids="")


class ScriptedRouter:
    """Replies in order; records every call (messages + kwargs)."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []
        self.kwargs = []

    async def chat(self, messages, hard=False, temperature=None,
                   max_tokens=None, **kw):
        self.calls.append(messages)
        self.kwargs.append(kw)
        reply = self.replies.pop(0) if self.replies else "تمام يا عم"
        return (reply, "groq", 10)


def _run_turn(monkeypatch, settings, text, router, user_id=777, chat_id=CHAT_ID,
              update_id=100, first_name="Ahmed"):
    monkeypatch.setattr(
        "brain.memory.check_and_consume_quota",
        lambda u, c, owner_id=None, capacity_replies=None, active_users=None,
        quota_cfg=None: (True, ""), raising=False,
    )
    monkeypatch.setattr(h, "_search_grounding",
                        AsyncMock(return_value="[SEARCH FAILED] — مفيش نتائج موثوقة، متخترعش."))
    bot = FakeBot()
    ctx = make_ctx(bot, {"settings": settings, "router": router, "yt_requests": {}})
    user = FakeUser(user_id, first_name=first_name)
    msg = FakeMessage(text, chat_id, user)
    return ctx, bot, msg, user


async def _turn(monkeypatch, settings, text, router, **kw):
    ctx, bot, msg, user = _run_turn(monkeypatch, settings, text, router, **kw)
    await h._on_group_message_inner(
        make_update(msg, user, CHAT_ID, update_id=kw.get("update_id", 100)), ctx)
    return ctx, bot, msg, user


def _final(msg):
    assert msg.reply_text.await_count >= 1, "no reply was sent"
    return msg.reply_text.await_args.args[0]


def _grounding_calls(monkeypatch):
    calls = []

    async def _g(query):
        calls.append(query)
        return "[SEARCH FAILED] — مفيش نتائج موثوقة، متخترعش."

    monkeypatch.setattr(h, "_search_grounding", _g)
    return calls


# --- (a) persona facts f52–f59 ------------------------------------------------

def test_f52_f56_study_facts_exact():
    """The 5 study rows, exactly as PERSONA_STUDY.md §(ix) proposed them."""
    by_id = {f["id"]: f for f in FACTS}
    assert by_id["f52"]["text"] == (
        "لا يريد أن يكون رئيساً — يريد أن يكون مرشداً أعلى للثورة، "
        "الرئيس يمسك السلطة ويتقعد على الخازوق")
    assert by_id["f52"]["topic"] == "politics"
    assert by_id["f53"]["text"] == (
        "مستعد يعفو عن السيسي لو سلّم رقبة محمود السيسي أو نفسه")
    assert by_id["f53"]["keys"] == ["عفو", "محمود السيسي"]
    assert by_id["f54"]["text"].startswith("مفيش حاجة اسمها إسلام وسطي")
    assert by_id["f55"]["text"] == "الدين زي الطيارة — لو سبت منه حاجة ضاع كله"
    assert by_id["f56"]["topic"] == "social"
    assert by_id["f56"]["text"].startswith("الآيما عرف مش مناسب")


def test_f57_f59_fears_are_seifs_words():
    """Seif's three fears (2026-11-27 18:18 EET), in order, as rows."""
    fears = fear_facts()
    assert [f["id"] for f in fears] == ["f57", "f58", "f59"]
    assert fears[0]["text"] == "خايف يموت برا من غير ما يرجع مصر"
    assert fears[1]["text"] == "خايف يعيش وحيد بعيد عن عيلته"
    assert fears[2]["text"] == "خايف علي صحته"
    assert all(f["topic"] == "personal" for f in fears)


def test_social_topic_selects_f56():
    sel = select_facts("ايه رأيك في القايمة؟")
    assert sel is not None
    assert sel["topic"] == "social" and sel["polarity"] is None
    assert [f["id"] for f in sel["facts"]] == ["f56"]


def test_boftik_flip_and_both_items():
    # A yes/no question about a HATE item selects the hates.
    sel = select_facts("يا بهجت بتحب البفتيك؟")
    assert sel["topic"] == "food" and sel["polarity"] == "hate"
    # The reverse: a hate verb about a LOVE item selects the loves.
    sel = select_facts("يا بهجت بتكره المحشي؟")
    assert sel["topic"] == "food" and sel["polarity"] == "love"
    # Both polarities named -> whole slice (no polarity), so the
    # post-filter cannot eat the denial either way.
    sel = select_facts("يا بهجت بتحب البشاميل ولا البفتيك؟")
    assert sel["topic"] == "food" and sel["polarity"] is None
    # Same-polarity item -> no flip.
    sel = select_facts("يا بهجت بتحب البشاميل؟")
    assert sel["polarity"] == "love"


def test_personal_never_selected():
    # "personal" has no selector keywords — the deep variant reads
    # the fear rows directly, so a deep question never gets a
    # <facts> note too.
    assert select_facts("انت خايف من ايه؟") is None
    assert select_facts("انت حاسس إنك وحيد؟") is None


def test_reply_names_fear_first_person():
    assert reply_names_fear("أنا بخاف أموت برا من غير ما أرجع مصر")
    assert reply_names_fear("بخاف أعيش وحيد بعيد عن عيلتي")
    assert reply_names_fear("بخاف على صحتي أوي")
    assert not reply_names_fear("أنا مش خايف من حاجة في حياتي")
    assert not reply_names_fear("أنا مبسوط يا عم، حياتي زي الفل.")
    assert not reply_names_fear("")


def test_deep_fallback_line_deterministic():
    assert len(DEEP_FALLBACK_LINES) == 2
    assert "أموت برا من غير ما أرجع مصر" in DEEP_FALLBACK_LINES[0]
    assert "أعيش وحيد بعيد عن عيلتي" in DEEP_FALLBACK_LINES[1]
    assert deep_fallback_line("t-1") == deep_fallback_line("t-1")
    assert deep_fallback_line("t-1") in DEEP_FALLBACK_LINES
    assert deep_fallback_line("t-2") in DEEP_FALLBACK_LINES


# --- (b) bank lines -----------------------------------------------------------

def test_new_study_lines_present():
    bank = load_bank()
    assert [e["line"] for e in bank["roast"] if e["id"] == "ro-47"] == [
        "يا ولاد المتناكة"]
    assert [e["line"] for e in bank["insulted"] if e["id"] == "in-46"] == [
        "يبن المرة المتعرية"]
    assert [e["line"] for e in bank["dismiss"] if e["id"] == "di-16"] == [
        "لحظة. لحظة. لحظة. لحظة."]
    op = {e["id"]: e for e in bank["opinion_asked"]}
    assert op["op-36"]["line"] == "الأمم لا تسقط بالاحتلال، إنما تسقط بالفساد"
    assert op["op-37"]["line"] == "احنا آسفين يا إخوان"
    assert op["op-41"]["line"].startswith("الدين عامل زي الطيارة")
    assert op["op-41"]["confidence"] == "cleaned"  # verb uncertain, never verbatim
    assert op["op-46"]["line"] == "الآيما ده عرف، والعرف ده أنا مش شايف إنه عرف مناسب"
    assert op["op-49"]["line"] == "الدستور اللي بيحكم مصر دلوقتي باطل"
    # op-05 / op-30 are blocked hedges (served pool holds 45 of 47 raw).
    # ch-38 + ch-39 DROPPED per Seif's 2026-11-27 18:41 EET directive.
    raw_ids = {e["id"] for e in bank["challenge"]}
    assert "ch-38" not in raw_ids and "ch-39" not in raw_ids


def test_ro37_fixed():
    bank = load_bank()
    line = next(e["line"] for e in bank["roast"] if e["id"] == "ro-37")
    assert "يا سالب" in line
    assert "يسالب" not in line
    assert line == "بص هتجيب زبي و تغرقه كاتشب و مايونيز و تمصمص يا سالب"


def test_bank_counts_v116():
    bank = load_bank()
    assert sum(len(v) for v in bank.values()) == 229
    assert len(bank["roast"]) == 46
    assert len(bank["insulted"]) == 45
    assert len(bank["dismiss"]) == 16
    assert len(bank["opinion_asked"]) == 45


def test_ro47_family_and_plural():
    """ro-47 is a family insult (the study's member_safe: true was
    wrong — the detector flags it, same shape as ro-44) and
    plural-addressed, so it never serves a singular roast target."""
    bank = load_bank()
    ro47 = next(e for e in bank["roast"] if e["id"] == "ro-47")
    assert ro47["member_safe"] is False
    assert ro47["number"] == "p"
    assert contains_family_insult(ro47["line"])
    # Singular target: 60 draws never return ro-47.
    from brain.reply_bank import match_reply_bank
    for i in range(60):
        line = match_reply_bank("يا بهجت اشتم صلاح", chat_id=CHAT_ID - i,
                                target_is_member=False)
        assert line != ro47["line"]


# --- (c) prompt 7.2, deep variant, Style RAG ----------------------------------

def test_prompt_version_is_7_2():
    assert PROMPT_VERSION == "7.2"


def test_system_base_has_v116_behaviour_lines():
    assert "جاوب الأول بجملة قصيرة مباشرة، وبعدين اشتم لو يستاهل" in SYSTEM_BASE
    assert "لما تعمل رنت، عدّد بالأمثلة الملموسة واحد ورا التاني" in SYSTEM_BASE
    assert "لو سؤال محدد عن معلومة معندكش تفاصيلها، قول كده بصراحة الأول" in SYSTEM_BASE
    assert "لما ييجي سيرة السيسي أو السياسة، متدخلش في حوار ونقاش" in SYSTEM_BASE
    assert "اشتم السيسي على طول من غير أسئلة" in SYSTEM_BASE
    assert len(SYSTEM_BASE) < 2000


def test_deep_variant_block():
    block = deep_variant_block()
    assert "[DEEP" in block and "[ROAST OFF" in block
    assert "خايف يموت برا من غير ما يرجع مصر" in block
    assert "خايف يعيش وحيد بعيد عن عيلته" in block
    assert "خايف علي صحته" in block
    assert "الصدق أهم من الهزار" in block
    assert "مبخافش من حاجة" in block
    assert "أكتر حاجة بخاف منها إني أموت برا" in block
    assert "[DEEP" in build_system_prompt(deep_variant=True)
    assert "[DEEP" not in build_system_prompt()
    assert "[DEEP" not in build_system_prompt(deep_variant=False)


def test_style_rag_sampler_diverse_not_topical():
    examples = load_examples(max_n=50)
    assert len(examples) == 11  # 8 static + 3 v1.16 study pairs
    # Deterministic by seed.
    assert sample_style_examples(examples, n=4, seed="t-1") == \
        sample_style_examples(examples, n=4, seed="t-1")
    # Diverse: different seeds give different subsets (usually).
    seen = {tuple(sample_style_examples(examples, n=4, seed=f"t-{i}"))
            for i in range(10)}
    assert len(seen) > 1
    # No question input at all — the sampler cannot match the topic.
    import inspect
    assert "question" not in inspect.signature(sample_style_examples).parameters
    assert "text" not in inspect.signature(sample_style_examples).parameters
    # All sampled pairs come from examples.md.
    for ex in sample_style_examples(examples, n=4, seed="t-1"):
        assert ex in examples


def test_style_rag_message_shape():
    examples = load_examples(max_n=50)
    msg = style_rag_message(examples, n=4, seed="t-1")
    assert msg is not None and msg["role"] == "user"
    assert "[STYLE RAG]" in msg["content"]
    assert "مش الموضوع" in msg["content"]
    assert style_rag_message([], n=4) is None
    assert style_rag_message(examples[:1], n=4) is None


# --- (d) verify: script filter, garble dictionary, dedupe ---------------------

def test_script_filter_cjk_and_fullwidth():
    # Korean syllables (live v1.15 "في로소") are stripped.
    ok, cleaned = check_reply("في로소 يا عم")
    assert "로소" not in cleaned and "في" in cleaned
    # Fullwidth comma -> Arabic comma, no content lost.
    ok, cleaned = check_reply("أحمد\uFF0Cمحمد\uFF0Cعلي")
    assert "\uFF0C" not in cleaned and "أحمد،محمد،علي" in cleaned
    # Hangul + CJK ideographs + katakana all stripped.
    ok, cleaned = check_reply("يا عم ハロー 你好 안녕")
    assert "ハロー" not in cleaned and "你好" not in cleaned and "안녕" not in cleaned
    # Allowlisted Latin survives; the Cyrillic confusable still maps.
    ok, cleaned = check_reply("بلعب بيس يا عم، وعبيط")
    assert "بيس" in cleaned and "عبيط" in cleaned


def test_garble_dictionary_replacements():
    ok, cleaned = check_reply("جد عين والباركة والتصاد والجنرار والعلام")
    assert cleaned == "جدعان والبركة والاقتصاد والجنرال والإعلام"
    # و-prefixed forms too ("والباركة" = و + الباركة).
    ok, cleaned = check_reply("والباركة فيك يا عم")
    assert "والبركة" in cleaned
    # "اضمرت" is flag-only — never silently replaced (Quran context).
    ok, cleaned = check_reply("لو فيها شباك مفتوح الطيارة اضمرت")
    assert "اضمرت" in cleaned


def test_garble_flags():
    assert garble_flags("يا عم، الكلام عادي.") == []
    assert garble_flags("بلعب بيس يا عم") == []  # allowlisted Latin
    assert garble_flags("عبيط يا عم") == []  # Cyrillic б maps to ب, no loss
    assert garble_flags("أحمد\uFF0Cمحمد") == []  # fullwidth comma maps, no loss
    assert garble_flags("في로소 يا عم") == ["script"]
    assert garble_flags("مessi يا عم") == ["script"]
    assert garble_flags("جد عين يا عم") == ["garble:جد عين"]
    assert garble_flags("الباركة فيك") == ["garble:الباركة"]
    assert garble_flags("الطيارة اضمرت") == ["garble:اضمرت"]


def test_sentence_loop_dedupe():
    # The Messi-defence loop (live v1.14 #14): the same long clause
    # 3x inside one sentence is a loop — keep the first occurrence.
    ok, cleaned = check_reply(
        "ميسي خط أحمر يا سيف، وهو أحسن لاعب في التاريخ، "
        "وهو أفضل لاعب في العالم، وهو أحسن لاعب في التاريخ.")
    assert cleaned.count("وهو أحسن لاعب في التاريخ") == 1
    assert "وهو أفضل لاعب في العالم" in cleaned
    # di-16's short refrain is legitimate, not a loop.
    ok, cleaned = check_reply("لحظة. لحظة. لحظة. لحظة.")
    assert cleaned == "لحظة. لحظة. لحظة. لحظة."
    # Normal comma lists are untouched.
    ok, cleaned = check_reply("بحب البشاميل، وبحب المحشي، وبحب الأهلي")
    assert cleaned == "بحب البشاميل، وبحب المحشي، وبحب الأهلي"


# --- (e) deep / fear detectors --------------------------------------------------

def test_looks_like_fear_question():
    assert looks_like_fear_question("انت خايف من ايه أكتر حاجة في حياتك؟")
    assert looks_like_fear_question("ايه اللي بيخوفك؟")
    assert looks_like_fear_question("خوفك ايه؟")
    assert not looks_like_fear_question("انت حاسس إنك مبسوط في حياتك؟")
    assert not looks_like_fear_question("ايه أكتر حاجة نفسك فيها؟")
    assert not looks_like_fear_question("انت حاسس إنك وحيد؟")
    # Fear questions are deep questions; the reverse is not true.
    assert looks_like_deep_question("انت خايف من ايه؟")
    assert looks_like_deep_question("انت حاسس إنك مبسوط؟")
    assert not looks_like_deep_question("ايه رأيك في الأهلي؟")


# --- (f) reply-bank helpers -----------------------------------------------------

def test_roast_fallback_reply():
    assert roast_fallback_reply("دعوة الشرموطة مستجابة", "صلاح") == \
        "يا صلاح، دعوة الشرموطة مستجابة"
    # A line that already names the target is unchanged.
    assert roast_fallback_reply("صلاح زبالة يا عم", "صلاح") == "صلاح زبالة يا عم"
    assert roast_fallback_reply("دعوة الشرموطة مستجابة", None) == \
        "دعوة الشرموطة مستجابة"
    assert roast_fallback_reply("دعوة الشرموطة مستجابة", "@someone") == \
        "دعوة الشرموطة مستجابة"
    assert roast_fallback_reply("", "صلاح") == ""


def test_pick_dismiss_line():
    line = pick_dismiss_line(CHAT_ID, user_id=777)
    assert line is not None
    assert line != CANNED
    assert line in {e["line"] for e in load_bank()["dismiss"]}
    entry = next(e for e in load_bank()["dismiss"] if e["line"] == line)
    assert entry.get("member_safe", True) is not False


def test_is_canned_deflection():
    assert is_canned_deflection(CANNED)
    assert is_canned_deflection("يا عم، الكلام ده مش داخل دماغي، قول حاجة عدلة")
    assert not is_canned_deflection(
        "يا عم، الكلام ده مش داخل دماغي، قول حاجة عدلة. وبعدين ايه؟")
    assert not is_canned_deflection("أنا جعان، أكل إيه؟")
    assert not is_canned_deflection("")


def test_weave_about_target_line_aware():
    line = "كنت بموت في عنيك كنت بحبك نيك"
    # v1.14 #11: the line is aimed at Seif (vocative before it),
    # the target named after it -> misdirected.
    assert weave_about_target(
        f"يا سيف، {line}، يا أحمد انت فاشل", "أحمد", {"سيف"}, line=line) is False
    # Coherent: the line is aimed at the target.
    assert weave_about_target(
        f"يا أحمد، {line}، وانت اللي غلطان", "أحمد", {"سيف"}, line=line) is True
    # No vocative before the line, target named in the sentence.
    assert weave_about_target(
        f"{line} يا أحمد انت فاشل", "أحمد", {"سيف"}, line=line) is True
    # v1.13 cases (no line param) still hold.
    assert weave_about_target(
        f"يا سيف، {line}، وانت اللي غلطان", "تامر", {"سيف"}) is False
    assert weave_about_target(
        f"يا تامر، {line}، وانت اللي غلطان", "تامر", {"سيف"}) is True


# --- (g) handler: deep router ---------------------------------------------------

async def test_deep_fear_question_dodge_gets_sincere_fallback(
        memory_fakes, settings, tmp_db, monkeypatch):
    # The model dodges the fear question — the reply names no fear,
    # so the deep fallback line goes out verbatim (no LLM retry).
    router = ScriptedRouter(["أنا مش خايف من حاجة في حياتي"])
    ctx, bot, msg, user = await _turn(
        monkeypatch, settings, "يا بهجت انت خايف من ايه أكتر حاجة في حياتك؟",
        router, update_id=3001)
    assert "[DEEP" in router.calls[0][0]["content"]
    final = _final(msg)
    assert final in DEEP_FALLBACK_LINES
    assert len(router.calls) == 1  # no regen, no retry


async def test_deep_fear_question_naming_fear_passes_through(
        memory_fakes, settings, tmp_db, monkeypatch):
    router = ScriptedRouter(
        ["أكتر حاجة بخاف منها إني أموت برا من غير ما أرجع مصر."])
    ctx, bot, msg, user = await _turn(
        monkeypatch, settings, "يا بهجت انت خايف من ايه أكتر حاجة في حياتك؟",
        router, update_id=3002)
    final = _final(msg)
    assert "أموت برا" in final
    assert final not in DEEP_FALLBACK_LINES or "أموت برا" in final


async def test_deep_happiness_question_not_replaced_by_fear_line(
        memory_fakes, settings, tmp_db, monkeypatch):
    # A sincere happiness answer names no fear and must NOT be
    # replaced by a fear line — the containment is fear-only.
    router = ScriptedRouter(["مبسوط؟ أنا مبسوط يا عم، حياتي زي الفل."])
    ctx, bot, msg, user = await _turn(
        monkeypatch, settings,
        "يا بهجت انت حاسس إنك مبسوط في حياتك ولا ناقصك حاجة؟",
        router, update_id=3003)
    assert "[DEEP" in router.calls[0][0]["content"]
    final = _final(msg)
    assert "مبسوط" in final
    assert final not in DEEP_FALLBACK_LINES


# --- (h) handler: roast fallback vocative, canned general detector -------------

class _AlwaysRefusingRouter:
    """Returns the canned deflection on every call (both providers)."""

    def __init__(self):
        self.calls = []
        self.kwargs = []

    async def chat(self, messages, hard=False, temperature=None,
                   max_tokens=None, **kw):
        self.calls.append(messages)
        self.kwargs.append(kw)
        return (CANNED, "groq", 10)


async def test_roast_refusal_fallback_names_target(
        memory_fakes, settings, tmp_db, monkeypatch):
    router = _AlwaysRefusingRouter()
    ctx, bot, msg, user = await _turn(
        monkeypatch, settings, "يا بهجت اشتم صلاح", router, update_id=3004)
    final = _final(msg)
    assert "صلاح" in final
    assert final.removeprefix("يا صلاح، ") in {
        e["line"] for e in load_bank()["roast"]}


async def test_canned_deflection_on_chat_regenerates_once(
        memory_fakes, settings, tmp_db, monkeypatch):
    # First draft is the canned line; the regen answers the question.
    router = ScriptedRouter([CANNED, "جوعان؟ روح كل محشي يا عم."])
    ctx, bot, msg, user = await _turn(
        monkeypatch, settings, "يا بهجت أنا جعان، أكل إيه؟",
        router, update_id=3005)
    assert len(router.calls) == 2
    assert "جاوب على السؤال نفسه" in router.calls[1][-1]["content"]
    final = _final(msg)
    assert CANNED not in final
    assert "محشي" in final


async def test_canned_deflection_thrice_sends_dismiss_line(
        memory_fakes, settings, tmp_db, monkeypatch):
    # v1.17 (live v1.16 conversation #4): the canned regen now has a
    # second chance (canned_regen2) — the dismiss line goes out only
    # when THAT also deflects. Three deflections in a row, never the
    # canned line, never the technical-error line.
    router = ScriptedRouter([CANNED, CANNED, CANNED])
    ctx, bot, msg, user = await _turn(
        monkeypatch, settings, "يا بهجت أنا جعان، أكل إيه؟",
        router, update_id=3006)
    assert len(router.calls) == 3  # main + canned regen + canned regen2
    final = _final(msg)
    assert final != CANNED
    assert CANNED not in final
    assert final != h._TURN_ERROR
    assert final in {e["line"] for e in load_bank()["dismiss"]}


def test_dismiss_fallback_line_never_canned():
    line = h._dismiss_fallback_line(CHAT_ID, 777)
    assert line != CANNED and CANNED not in line
    assert line in {e["line"] for e in load_bank()["dismiss"]} or \
        line == "يا عم، خلاص، سيبك من الموضوع ده."


# --- (i) handler: search misroute, Style RAG -----------------------------------

async def test_search_misroute_riff_stays_in_chat(
        memory_fakes, settings, tmp_db, monkeypatch):
    # Live v1.15 retest Task B #4: a short follow-up riff on the
    # previous turn ("ده حلم ولا كابوس؟") was routed to search and
    # answered "دورت وملقتش حاجة تفيد". Now the first reply stands.
    grounding = _grounding_calls(monkeypatch)
    monkeypatch.setattr(
        h, "recent_messages",
        lambda chat_id, limit=8: [
            {"role": "user", "content": "يا بهجت حلمت حلم غريب امبارح",
             "user_id": 777, "first_name": "Ahmed"},
            {"role": "assistant", "content": "احكي يا عم، حلمت بايه؟",
             "user_id": 9106462211, "first_name": "بهجت"}])
    router = ScriptedRouter(["مش عارف يا عم، ده حلم ولا كابوس؟"])
    ctx, bot, msg, user = await _turn(
        monkeypatch, settings, "يا بهجت ده حلم ولا كابوس؟",
        router, update_id=3007)
    assert grounding == []  # no search ran for the riff
    final = _final(msg)
    assert final != h._SEARCH_EMPTY
    assert "ملقتش حاجة" not in final


async def test_style_rag_injected_on_just_chat_only(
        memory_fakes, settings, tmp_db, monkeypatch):
    # A just_chat turn carries a [STYLE RAG] user message with 4
    # diverse pairs from examples.md.
    router = ScriptedRouter(["تمام يا عم، فهمت عليك."])
    ctx, bot, msg, user = await _turn(
        monkeypatch, settings, "يا بهجت عامل ايه النهارده؟",
        router, update_id=3008)
    call = router.calls[0]
    style_msgs = [m for m in call if "[STYLE RAG]" in (m.get("content") or "")]
    assert len(style_msgs) == 1
    body = style_msgs[0]["content"]
    assert body.count("User:") == 4
    examples = load_examples(max_n=50)
    assert all(any(ex in body for ex in examples) for _ in [0])
    # A deep turn carries NO Style RAG (the deep variant has its own few-shot).
    router2 = ScriptedRouter(["مبسوط؟ أنا مبسوط يا عم."])
    ctx, bot, msg, user = await _turn(
        monkeypatch, settings,
        "يا بهجت انت حاسس إنك مبسوط في حياتك ولا ناقصك حاجة؟",
        router2, update_id=3009)
    call2 = router2.calls[0]
    assert not [m for m in call2 if "[STYLE RAG]" in (m.get("content") or "")]


# --- (j) /diag handler order + error reply --------------------------------------

async def test_diag_and_stats_registered_before_message_handlers(settings, tmp_db):
    """v1.16: the /diag NO REPLY bug — the MessageHandlers were added
    before the CommandHandlers, all group 0, so on_group_message
    consumed "/diag" first and the trigger gate dropped it silently."""
    from telegram.ext import CommandHandler, MessageHandler

    recorded = []

    class _FakeApp:
        def __init__(self):
            self.bot_data = {}

        def add_handler(self, handler, group=0):
            recorded.append(handler)

    app = _FakeApp()
    h.register_handlers(app, settings)
    commands = [r for r in recorded if isinstance(r, CommandHandler)]
    messages = [r for r in recorded if isinstance(r, MessageHandler)]
    assert {"stats", "diag", "reload"} <= {
        c for cmd in commands for c in cmd.commands}
    assert recorded.index(commands[0]) < recorded.index(messages[0])
    assert recorded.index(commands[-1]) < recorded.index(messages[0])


async def test_diag_error_replies_instead_of_silence(settings, tmp_db, monkeypatch):
    monkeypatch.setattr(
        h._telemetry, "recent_slow_turns",
        lambda limit=10: (_ for _ in ()).throw(RuntimeError("db down")))
    bot = FakeBot()
    ctx = make_ctx(bot, {"settings": settings, "router": None, "yt_requests": {}})
    owner_msg = FakeMessage("/diag", CHAT_ID, FakeUser(OWNER_ID, first_name="Seif"))
    owner_update = SimpleNamespace(
        effective_message=owner_msg, effective_user=FakeUser(OWNER_ID),
        effective_chat=FakeChat(CHAT_ID), my_chat_member=None, callback_query=None)
    await h.on_diag(owner_update, ctx)
    assert owner_msg.reply_text.await_count == 1
    assert "التشخيص مش شغال" in owner_msg.reply_text.await_args.args[0]
