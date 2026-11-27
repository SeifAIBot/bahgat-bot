"""v1.6 phase 1 user-submitted ingest round 3: Seif added 12 more insult
lines on the "قاموس شتايم بهجت" page (2026-11-26), bringing the page total
to 45 (24 round 1 + 9 round 2 + 12 round 3). 10 were banked (5 insulted
comebacks in-41..in-45, 5 roasts ro-42..ro-46); 2 were dropped — "قوم يا
مصري مصر دايما ب تناديك قوم يا ايبنللللللللل مش هنتحايل عليك"
(near-duplicate of the round-1 dropped rallying line "قووم يا مصري مش
هنتحايل عليك": still a patriotic chant, not an insult) and "خخخخخ ايوه
خخخخخخ ايوه" (mocking laughter only, not an insult). One resubmission
("ايه الشرمطه دي") was skipped by the page itself as an exact duplicate
of round-2's in-34, so it is not double-banked.
Two family lines this round: ro-42 (Seif marked it "للبرّه بس" — the
detector agrees) and ro-44 ("يا ولاد ال..." — the detector's "يا ولاد"
branch flags it even though Seif tagged the line member_safe on the
page; the detector wins, so it is banked member_safe: false in the roast
pool and never served at a member). The Mido line is the first
subject-targeted user roast (ro-43, target: ميدو).
Owner-authored lines (confidence "user", source "user-submitted") are
served like verbatim/cleaned; they are never presented as Bahgat
transcript lines.
"""
from pathlib import Path

import pytest
import yaml

from brain import reply_bank as rb
from brain.reply_bank import load_bank, match_reply_bank, reload_bank

CHAT_ID = -1005812444791

# The 12 lines Seif added in round 3 (page order, oldest first).
NEW_SUBMITTED = [
    "ابن متناكه و ماشي، مغفل و ماشي ، بتاخد من طيزك يطلع من بقك و ماشي لكن غبي يبن المتناكه كمان",
    "يا ميدو مسمعش صوت ، لا عيب يا ميدو عيب",
    "عايزين نعملك بني ادم يكلب و انتا مصمم هحهحهحهح ، منا عايز اعملك بني ادم انتا مصمم تبقا حيوان ليه",
    "قوم يا مصري مصر دايما ب تناديك قوم يا ايبنللللللللل مش هنتحايل عليك",
    "انا راجل بتاع نسوان ، و الحمد لله معايا مراتي و ميه ميه و فل ربنا تاب علينا يا ابن ال مليش انا في الخولات الزيك يعرص",
    "عايز ايه ياض يا خول عايز ايه ياض يخول عايز ايه يخول",
    "عليا النعمه انتا اكيد عايز تتناك",
    "انا اهو يا متناكين انا اهووو",
    "خخخخخ ايوه خخخخخخ ايوه",
    "بعبصو بعض في حته تانيه يا ولاد ال هو مفيش غير الخرابه دي",
    "يا متناك يا علق يا عاهر يا داعر يا ملعوب في طيزك ب زوبر حمار وحشي يخول",
    "قالو ايه قالو ايه خده في طيزه يا سعادت البيه قالو ايه قالو ايه خده في طيزه يا سعادت البيه",
]

NEW_INSULTED = [
    "عايزين نعملك بني ادم يكلب و انتا مصمم هحهحهحهح ، منا عايز اعملك بني ادم انتا مصمم تبقا حيوان ليه",
    "انا راجل بتاع نسوان ، و الحمد لله معايا مراتي و ميه ميه و فل ربنا تاب علينا يا ابن ال مليش انا في الخولات الزيك يعرص",
    "عايز ايه ياض يا خول عايز ايه ياض يخول عايز ايه يخول",
    "عليا النعمه انتا اكيد عايز تتناك",
    "انا اهو يا متناكين انا اهووو",
]

NEW_ROAST = [
    "ابن متناكه و ماشي، مغفل و ماشي ، بتاخد من طيزك يطلع من بقك و ماشي لكن غبي يبن المتناكه كمان",
    "يا ميدو مسمعش صوت ، لا عيب يا ميدو عيب",
    "بعبصو بعض في حته تانيه يا ولاد ال هو مفيش غير الخرابه دي",
    "يا متناك يا علق يا عاهر يا داعر يا ملعوب في طيزك ب زوبر حمار وحشي يخول",
    "قالو ايه قالو ايه خده في طيزه يا سعادت البيه قالو ايه قالو ايه خده في طيزه يا سعادت البيه",
]

# The two round-3 family lines (member_safe: false, roast pool only).
FAMILY_ROAST = {
    "ابن متناكه و ماشي، مغفل و ماشي ، بتاخد من طيزك يطلع من بقك و ماشي لكن غبي يبن المتناكه كمان",
    "بعبصو بعض في حته تانيه يا ولاد ال هو مفيش غير الخرابه دي",
}

MIDO_LINE = "يا ميدو مسمعش صوت ، لا عيب يا ميدو عيب"

# The two dropped round-3 lines stay out.
DROPPED = {
    "قوم يا مصري مصر دايما ب تناديك قوم يا ايبنللللللللل مش هنتحايل عليك",
    "خخخخخ ايوه خخخخخخ ايوه",
}

# Round-1 dropped lines stay out (unchanged by round 3).
STILL_DROPPED = {
    "يا حبيبي يا مصر يا مصر يا حبيبتي يا مصر يا مصر",
    "قووم يا مصري مش هنتحايل عليك",
    "مصممممممص",
}


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
def _reset_bank_state():
    reload_bank()
    yield
    reload_bank()


def _raw():
    return yaml.safe_load(open(
        Path(__file__).resolve().parents[1] / "persona/bahgat/reply_bank.yaml",
        encoding="utf-8"))["entries"]


def test_round3_lines_all_banked_with_ids():
    raw = _raw()
    banked_lines = {e["line"] for e in raw}
    for ln in NEW_INSULTED + NEW_ROAST:
        assert ln in banked_lines, ln
    for ln in DROPPED | STILL_DROPPED:
        assert ln not in banked_lines, ln
    assert len(NEW_SUBMITTED) == 12
    assert len(NEW_INSULTED) == 5
    assert len(NEW_ROAST) == 5
    user = [e for e in raw if e.get("confidence") == "user"]
    assert len(user) == 40  # 21 round 1 + 9 round 2 + 10 round 3
    by_line = {e["line"]: e for e in user}
    assert {by_line[ln]["id"] for ln in NEW_INSULTED} == {
        f"in-{i:02d}" for i in range(41, 46)
    }
    assert {by_line[ln]["id"] for ln in NEW_ROAST} == {
        f"ro-{i:02d}" for i in range(42, 47)
    }
    for ln in NEW_INSULTED:
        assert by_line[ln]["trigger"] == "insulted"
    for ln in NEW_ROAST:
        assert by_line[ln]["trigger"] == "roast"


def test_round3_lines_honest_attribution_and_tags():
    raw = _raw()
    user = [e for e in raw if e.get("confidence") == "user"]
    new = [e for e in user
           if e["line"] in NEW_INSULTED + NEW_ROAST]
    assert len(new) == 10
    for e in new:
        assert e["source"] == "user-submitted"
        assert e.get("member_safe") in (True, False)
    # Exactly the two family lines are non-member-only; the rest are
    # person-only. The Mido line is subject-targeted; the other new
    # roasts are generic.
    by_line = {e["line"]: e for e in new}
    for ln in FAMILY_ROAST:
        assert by_line[ln]["member_safe"] is False
    for e in new:
        if e["line"] not in FAMILY_ROAST:
            assert e["member_safe"] is True
    assert by_line[MIDO_LINE]["target"] == "ميدو"
    assert all(e.get("target") is None for e in new
               if e["trigger"] == "roast" and e["line"] != MIDO_LINE)
    # The family detector must agree: it flags exactly the two family
    # lines among the 10 new ones (and, over all user lines, exactly
    # ro-40 + the two new ones).
    from core.rules import contains_family_insult
    flagged_new = [e["line"] for e in new
                   if contains_family_insult(e["line"])]
    assert set(flagged_new) == FAMILY_ROAST
    flagged_user = {e["id"] for e in user
                    if contains_family_insult(e["line"])}
    assert flagged_user == {"ro-40", "ro-42", "ro-44"}


def test_round3_insulted_pool_counts():
    bank = load_bank()
    assert len(bank["insulted"]) == 44
    user_insulted = [e for e in bank["insulted"]
                     if e.get("confidence") == "user"]
    assert len(user_insulted) == 30  # 17 round 1 + 8 round 2 + 5 round 3
    assert all(e.get("member_safe") is True for e in user_insulted)


def test_round3_roast_reachable_and_targeted():
    bank = load_bank()
    assert len(bank["roast"]) == 45
    user_roast = [e for e in bank["roast"]
                  if e.get("confidence") == "user"]
    assert len(user_roast) == 10  # 4 round 1 + 1 round 2 + 5 round 3
    generic = {e["line"] for e in bank["roast"]
               if e.get("target") is None}
    assert len(generic) == 19  # v1.13: ro-39 targets كريستيانو
    # A roast of anyone else never serves the Mido line.
    for text in ("اشتم صلاح", "يا بهجت اشتم صلاح"):
        seen = {
            match_reply_bank(text, chat_id=CHAT_ID, target_is_member=False)
            for _ in range(60)
        } - {None}
        assert seen <= generic
        assert MIDO_LINE not in seen
    # A roast of ميدو may serve the Mido line (and only generic + ميدو).
    seen_mido = {
        match_reply_bank("اشتم ميدو", chat_id=CHAT_ID,
                         target_is_member=False)
        for _ in range(200)
    } - {None}
    assert seen_mido <= generic | {MIDO_LINE}
    assert MIDO_LINE in seen_mido


def test_round3_family_lines_never_served_to_members(monkeypatch):
    # Deterministic check for the member side (choice = last eligible):
    # ro-46 is the last roast entry and is member-safe, so the member
    # pick is never a family line.
    monkeypatch.setattr(rb.random, "choice", lambda xs: xs[-1])
    for ln in FAMILY_ROAST:
        assert match_reply_bank(
            "يا بهجت اشتم محمد", chat_id=CHAT_ID,
            target_is_member=True) != ln
        assert match_reply_bank(
            "يا بهجت اشتم محمد", chat_id=CHAT_ID,
            target_is_member=None) != ln
    # Non-member reachability: sample many draws; both family lines
    # must appear (they are in the non-member generic pool). v1.13:
    # ro-40 is plural-addressed ("يا ولاد..."), so the draws use the
    # plural imperative — a bare singular roast correctly never draws
    # it, while ro-42 (singular) would appear either way.
    monkeypatch.undo()
    seen = {
        match_reply_bank(
            "يا بهجت اشتموا محمد", chat_id=CHAT_ID,
            target_is_member=False)
        for _ in range(300)
    }
    assert FAMILY_ROAST <= seen


def test_round3_no_duplicates():
    raw = _raw()
    lines = [e["line"] for e in raw]
    assert len(lines) == len(set(lines))
    assert len(raw) == 224
    user_lines = [e["line"] for e in raw
                  if e.get("confidence") == "user"]
    assert len(user_lines) == len(set(user_lines)) == 40


def test_round3_resubmitted_duplicate_not_double_banked():
    # Seif resubmitted "ايه الشرمطه دي" in round 3; the page skipped it
    # as an exact duplicate of round-2's in-34 — it must appear once.
    raw = _raw()
    hits = [e for e in raw if e["line"] == "ايه الشرمطه دي"]
    assert len(hits) == 1
    assert hits[0]["id"] == "in-34"
