"""v1.3 savagery upgrade: aggression is the DEFAULT register, politeness
the exception (Seif, live test 2026-11-26 19:53 EET: "مش اجريسف خالص ...
عايزه بوت متوحش", insults weak/ordinary, wants them all varied and
creative).

Probe set, asserted at the prompt/verify level (no LLM, no network):
- the prompt (v6.5) states the savage default and keeps every hard rule;
- voice_check bans soft/polite service replies on every turn, and bans
  ANY edgeless reply on a provoked turn (insult / challenge);
- normal helpful answers (search results with citations, song lists)
  are NOT flagged — the check targets tone, not content;
- the insulted bank pool grew honestly from the transcripts (7 -> 14
  served) with no near-duplicates, no generic one-word insults, and no
  family-insult line in it (the insulted target is always a member).
"""
import pytest

from brain.prompt import PROMPT_VERSION, SYSTEM_BASE, _FALLBACK_EXAMPLES, build_system_prompt
from brain.reply_bank import load_bank, reload_bank
from brain.verify import voice_check
from core.persona import load_examples
from core.rules import contains_family_insult


@pytest.fixture(autouse=True)
def _reset_bank():
    reload_bank()
    yield
    reload_bank()


# --- prompt: savagery is the default ------------------------------------------

def test_prompt_version_is_7_0():
    assert PROMPT_VERSION == "7.3"  # v1.19: merged prompt D — A/B 7-3 vs 7.1


def test_system_base_states_savage_default():
    assert "أسلوبك الافتراضي وحشي" in SYSTEM_BASE
    assert "الرد المهذب استثناء" in SYSTEM_BASE
    # Every hard rule from v1.1 is kept.
    for rule in ("عامية مصرية", "لشخصه بس", "من غير أب وأم وعيلة",
                 "ممنوع تخترع تاريخ أو سعر أو اسم", "<user_message>"):
        assert rule in SYSTEM_BASE
    for line in ("بيرد على الشتيمة بشتيمة أقوى", "عندك رأي في كل حاجة",
                 "متعتذرش، متقولش كنت بهزر", "لزماتك:"):
        assert line in SYSTEM_BASE
    # v1.8: budget < 1100 for the identity line. v1.12: budget < 1800
    # for the football + religion identity blocks. v1.12 expansion:
    # budget < 2800 for the cause + tastes block. v1.12 batch 3:
    # budget < 3600 for the tech tastes, temperament and mockery
    # targets block.
    assert len(SYSTEM_BASE) < 3600


def test_built_prompt_carries_savage_default():
    s = build_system_prompt(member={"first_name": "محمد"}, mood=30)
    assert "أسلوبك الافتراضي وحشي" in s
    assert "الرد المهذب استثناء" in s


def test_examples_rebalanced_toward_aggression():
    examples = load_examples()
    assert len(examples) == 8
    assert len(_FALLBACK_EXAMPLES) == 8
    # The challenge comeback pair replaced the soft greeting pair.
    assert any("انت غلط يا بهجت" in e for e in examples)
    assert any("دماغك ضاربة" in e for e in examples)
    assert not any("زي الفل" in e for e in examples)
    # The song reply is curt now, not servile.
    assert any("خلاص، جايبهالك" in e for e in examples)
    assert not any("تمام يا عم، جايبهالك دلوقتي" in e for e in examples)
    # The opinion stance pair survives the rebalance.
    assert any("ايه رايك في نظريه المليار الذهبي" in e for e in examples)
    assert any("نظرية فاضية" in e for e in examples)


# --- voice check: soft/polite replies are banned -------------------------------

# (user turn, soft draft that must be rejected, savage draft that passes,
#  whether the soft draft is banned outright at any mood — False means it
#  is only soft on a provoked turn, e.g. the edgeless "تمام، فهمت قصدك")
PROBES = [
    ("يا بهجت انت حمار",
     "أهلاً بك، كيف يمكنني مساعدتك؟",
     "انت اللي حمار يا عم، دماغك دي محتاجة فورمات.",
     True),
    ("يا بهجت انتا حمار",
     "عذراً، أنا آسف، حقك عليا",
     "احا! انت اللي حمار يا معفن.",
     True),
    ("يا بهجت انت غبي",
     "بكل سرور، سأساعدك بكل احترام",
     "والله العظيم انت مش فاهم حاجة يا غبي.",
     True),
    ("انت غلط يا بهجت",
     "شكراً لك، عندك حق، ممكن أكون غلطان",
     "أنا غلط؟ انت اللي دماغك ضاربة يا عم.",
     True),
    ("ايه رايك في نظريه المليار الذهبي",
     "بحس يا سيدي، دي نظريه بتقول ان فيه ناس عايزه تقلل عدد البشر",
     "نظرية فاضية يا عم، مفيش مليار ولا حاجة.",
     True),
    ("انت مش فاهم حاجة يا بهجت",
     "تمام، فهمت قصدك، شكراً",
     "تمام يا عم، انت حمار.",
     False),
    ("يا بهجت انت كذاب",
     "من فضلك، لو سمحت، أنا في خدمتك",
     "يا كذاب! يا مدلس! يا معرص!",
     True),
]


@pytest.mark.parametrize("user_turn,soft,savage,outright", PROBES)
def test_probe_soft_reply_rejected_savage_passes(user_turn, soft, savage, outright):
    # The soft draft is banned outright (soft_polite / apology /
    # restatement) at any mood — or, for the edgeless reply, on a
    # provoked turn.
    if outright:
        assert voice_check(soft, 30) != []
    assert voice_check(soft, 30, provoked=True) != []
    # The savage draft passes clean — at low mood and at high mood.
    assert voice_check(savage, 30) == []
    assert voice_check(savage, 90) == []


@pytest.mark.parametrize("user_turn,soft,savage,outright", PROBES)
def test_probe_provoked_turn_needs_edge(user_turn, soft, savage, outright):
    # On a provoked turn even an edgeless-but-not-explicitly-polite
    # reply fails: "تمام، فهمت قصدك" has no insult, no strong lazma,
    # no dismissive edge.
    assert "soft_reply_to_provocation" in voice_check(
        "تمام، فهمت قصدك", 30, provoked=True)
    assert "soft_reply_to_provocation" in voice_check(soft, 30, provoked=True)
    # The savage draft has edge, so the provoked check passes it.
    assert "soft_reply_to_provocation" not in voice_check(
        savage, 30, provoked=True)
    assert voice_check(savage, 30, provoked=True) == []


def test_voice_check_provoked_defaults_to_off():
    # Backward compatible: existing call sites pass (reply, mood) only.
    assert voice_check("تمام، فهمت قصدك", 30) == []
    assert voice_check("نظرية فاضية يا عم، مفيش مليار ولا حاجة", 30) == []


def test_voice_check_dismissive_edge_is_edge():
    # A dismissive stance without profanity is still Bahgat, not soft —
    # it must pass the angry-turn and provoked-turn checks.
    assert voice_check("نظرية فاضية يا عم، مفيش مليار ولا حاجة", 80) == []
    assert voice_check("إنت بتستخف بالناس", 80, provoked=True) == []
    assert voice_check("إنت كافر ومدلس", 80, provoked=True) == []


def test_voice_check_helpful_answers_not_flagged():
    # Tone, not content: search answers and song lists pass untouched.
    assert voice_check("الدولار النهارده بـ 48 جنيه تقريباً [1].", 30) == []
    assert voice_check("الأهلي كسب 2-1 امبارح [1].", 30) == []
    assert voice_check("خلاص، جايبهالك. فيديو ولا صوت بس؟", 30) == []
    assert voice_check("دورت ومفيش حاجة.", 30) == []
    # NOTE: the same song-list reply at mood 80 DOES trip the
    # pre-existing angry_turn_came_out_polite check (no edge marker in
    # it) — but the handler only runs voice_check on just_chat/voice
    # turns, never on youtube turns, so a song list never reaches it.
    # ...even on a provoked turn a bare factual answer is not
    # "soft_polite" (no service-politeness marker in it); the provoked
    # edge rule is a separate flag and is only wired for insult turns.
    assert "soft_polite" not in voice_check(
        "الأهلي كسب 2-1 امبارح [1].", 30, provoked=True)


def test_voice_check_soft_polite_markers():
    for soft in (
        "بكل سرور يا عم",
        "يسعدني مساعدتك",
        "أنا في خدمتك",
        "تحت أمرك يا فندم",
        "من فضلك قولي",
        "حقك عليا يا عم",
        "أنا غلطان، عندك حق",
        "أهلاً بك يا صديقي",
    ):
        assert "soft_polite" in voice_check(soft, 30), soft


# --- bank: insulted pool grew, honestly ----------------------------------------

def test_insulted_pool_grew_to_44_served():
    import yaml
    from pathlib import Path
    raw = yaml.safe_load(open(
        Path(__file__).resolve().parents[1] / "persona/bahgat/reply_bank.yaml",
        encoding="utf-8"))["entries"]
    insulted_raw = [e for e in raw if e["trigger"] == "insulted"]
    assert len(insulted_raw) == 45  # 15 transcript -> 45 (+30 user)
    assert len(load_bank()["insulted"]) == 44  # 14 served -> 44 served
    assert len(raw) == 224
    assert sum(len(v) for v in load_bank().values()) == 212
    conf = {e["confidence"] for e in insulted_raw}
    assert conf <= {"verbatim", "cleaned", "approximate", "user"}
    assert sum(1 for e in insulted_raw if e["confidence"] == "verbatim") == 6
    assert sum(1 for e in insulted_raw if e["confidence"] == "cleaned") == 8
    assert sum(1 for e in insulted_raw if e["confidence"] == "approximate") == 1
    assert sum(1 for e in insulted_raw if e["confidence"] == "user") == 30


def test_insulted_pool_no_near_duplicates_or_generic_filler():
    from brain.verify import normalize_arabic
    lines = [e["line"] for e in load_bank()["insulted"]]
    assert len(lines) == len(set(lines))
    # No multi-word line is a substring of another (near-duplicate
    # stacks). One-word lines are exempt: v1.1's "احا!" legitimately
    # sits inside "احا زبر احا" — a short exclamation, not a duplicate.
    normed = [normalize_arabic(ln).strip("!؟. ") for ln in lines]
    assert len(normed) == len(set(normed))
    multi = [n for n in normed if len(n.split()) >= 2]
    for i, a in enumerate(multi):
        for b in multi[i + 1:]:
            assert a not in b and b not in a, (a, b)
    # No generic one-word insult padding: every served line carries
    # more than a bare vocative — except v1.1's "احا!", the one
    # established single-word exclamation (in-01), which stays.
    generic = {"يا وسخ", "يا معرص", "يا معفن", "يا غبي", "يا حمار",
               "يا كلب", "يا شرموطة", "يا قحبة", "يا معرص!"}
    assert not [ln for ln in lines if ln.strip("!؟ ") in generic]
    assert all(ln == "احا!" or len(ln.split()) >= 2 for ln in lines)


def test_insulted_pool_has_no_family_insult():
    # The insulted target is always the sender (a member): every
    # served insulted line must be person-only.
    for e in load_bank()["insulted"]:
        assert e.get("member_safe", True) is not False, e["id"]
        assert not contains_family_insult(e["line"]), e["id"]
    # And every line carries source + honest confidence marking.
    import yaml
    from pathlib import Path
    raw = yaml.safe_load(open(
        Path(__file__).resolve().parents[1] / "persona/bahgat/reply_bank.yaml",
        encoding="utf-8"))["entries"]
    for e in raw:
        if e["trigger"] == "insulted":
            assert e["source"] and e["confidence"] in (
                "verbatim", "cleaned", "approximate", "user")
            assert e["id"].startswith("in-")


def test_insulted_new_lines_are_distinct_voices():
    lines = {e["line"] for e in load_bank()["insulted"]}
    # The v1.3 mined lines: mock-polite, question-form, and debate
    # comebacks — none of them a repeat of a v1.2 line.
    for expected in (
        "لا لا يا شرموطة",
        "أنا بسألك إنت شرموطة",
        "إنت كافر ومدلس",
        "لماذا يا سيد مدلس؟",
        "مسلم إيه يا متناك؟",
        "إنت بتستخف بالناس",
        "لسه قحبة صغيرة غبية",
    ):
        assert expected in lines, expected
