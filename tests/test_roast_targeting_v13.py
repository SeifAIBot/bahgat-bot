"""v1.3 roast targeting: a target-specific bank line fires ONLY for its
subject (live bug 2026-11-26 19:54 EET: "اشتم صلاح" served ro-21
"عاوز يغير في القرآن يا متناك؟" — a Sisi line about Sisi wanting to
change the Quran — for صلاح, who is not a group member).

Mechanism (brain/reply_bank.py, roast branch): the roast branch passed
extract_insult_target(text) only to the member/owner gates; _pick()
then chose at random from the WHOLE 35-line roast pool with only the
member_safe filter. The target name was never used to filter lines, so
any roast line — Sisi lines, Lina lines, the Kissinger line, the train
carriage line — could serve for any target.

Fix: roast entries carry an optional `target:` field in the YAML (the
subject the line is about); _pick(target=...) serves only generic
lines (no `target:`) plus lines whose subject matches the roast target
(normalised substring match + a small alias map). No fitting line ->
generic lines only; no generic lines either -> None, never a
non-sequitur.
"""
from pathlib import Path

import pytest
import yaml

from brain import reply_bank as rb
from brain.reply_bank import (
    _pick,
    _target_matches,
    load_bank,
    match_reply_bank,
    reload_bank,
)

CHAT_ID = -1005812444791
QURAN_LINE = "عاوز يغير في القرآن يا متناك؟"
SISI_LINE = "السيسي ده حيوان، حمار كداب"


@pytest.fixture(autouse=True)
def _reset_bank_state():
    reload_bank()
    yield
    reload_bank()


def _roast_entries():
    return load_bank()["roast"]


def _lines(entries):
    return {e["line"] for e in entries}


def _generic_lines(member_safe_only=False):
    entries = _roast_entries()
    if member_safe_only:
        entries = [e for e in entries if e.get("member_safe", True) is not False]
    return _lines([e for e in entries if e.get("target") is None])


def _subject_lines(subject, member_safe_only=False):
    entries = _roast_entries()
    if member_safe_only:
        entries = [e for e in entries if e.get("member_safe", True) is not False]
    return _lines([e for e in entries if e.get("target") == subject])


def _draws(text, n, **kwargs):
    return {
        match_reply_bank(text, chat_id=CHAT_ID, **kwargs)
        for _ in range(n)
    } - {None}


# --- YAML shape ---------------------------------------------------------------

def test_yaml_roast_target_field_shape():
    raw = yaml.safe_load(open(
        Path(__file__).resolve().parents[1] / "persona/bahgat/reply_bank.yaml",
        encoding="utf-8"))["entries"]
    roast = [e for e in raw if e["trigger"] == "roast"]
    assert len(roast) == 46  # 45 served + ro-29 (approximate, never served)
    tagged = [e for e in roast if e.get("target") is not None]
    generic = [e for e in roast if e.get("target") is None]
    assert len(tagged) == 26
    assert len(generic) == 20  # 11 transcript + 9 user-submitted (ro-37..42, ro-44..46)
    # Subjects are the people/situations the lines are actually about.
    assert {e["target"] for e in tagged} == {
        "السيسي", "لينا", "الجيش", "ندوش", "المسيحي",
        "كيسنجر", "كارما", "حادثة القطار", "ضيوف اللايف",
        "ميدو",
    }
    for e in tagged:
        assert isinstance(e["target"], str) and e["target"].strip()
    # The bug line is tagged with its real subject; the control line too.
    by_id = {e["id"]: e for e in roast}
    assert by_id["ro-21"]["line"] == QURAN_LINE
    assert by_id["ro-21"]["target"] == "السيسي"
    assert by_id["ro-04"]["target"] == "السيسي"
    # Served counts unchanged by tagging (v1.2 counts still hold).
    assert len(_roast_entries()) == 45  # 35 transcript + 10 user-submitted
    assert len([e for e in _roast_entries() if e.get("target")]) == 25


# --- matcher units ------------------------------------------------------------

def test_target_matches_unit():
    assert _target_matches(None, "صلاح") is True  # generic fits anyone
    assert _target_matches("السيسي", "السيسي") is True
    assert _target_matches("السيسي", "سيسي") is True  # bare form
    assert _target_matches("السيسي", "بلحة") is True  # alias
    assert _target_matches("السيسي", "بلحه") is True  # normalised alias
    assert _target_matches("السيسي", "صلاح") is False
    assert _target_matches("السيسي", "محمد") is False
    assert _target_matches("كارما", "كارما") is True
    assert _target_matches("كارما", "صلاح") is False
    assert _target_matches("لينا", "لينا") is True
    assert _target_matches("لينا", "صلاح") is False
    assert _target_matches("الجيش", "الجيش") is True
    assert _target_matches("الجيش", "صلاح") is False
    assert _target_matches("كيسنجر", "كسينجر") is True  # spelling alias
    assert _target_matches("المسيحي", "مسيحي") is True
    assert _target_matches("المسيحي", "صلاح") is False
    assert _target_matches("السيسي", None) is False
    assert _target_matches("السيسي", "") is False


def test_pick_target_filter_synthetic(monkeypatch):
    # Deterministic: one generic + one Sisi + one Karma line.
    rb._bank_cache = {"roast": [
        {"id": "ro-x", "line": "يا معفن", "trigger": "roast"},
        {"id": "ro-y", "line": "السيسي ده حيوان", "trigger": "roast",
         "target": "السيسي"},
        {"id": "ro-z", "line": "يعني انتي بتلحسي خرى للعيال",
         "trigger": "roast", "target": "كارما"},
    ]}
    rb._last_used.clear()
    monkeypatch.setattr(rb.random, "choice", lambda xs: xs[-1])
    # Last eligible line for صلاح is the generic one (Sisi/Karma excluded).
    assert _pick("roast", CHAT_ID, target="صلاح") == "يا معفن"
    # For السيسي the Sisi line is eligible and last.
    assert _pick("roast", CHAT_ID, target="السيسي") == "السيسي ده حيوان"
    # For كارما the Karma line is eligible and last.
    assert _pick("roast", CHAT_ID, target="كارما") == (
        "يعني انتي بتلحسي خرى للعيال")
    # No target filter at all (other categories) keeps the old behaviour.
    assert _pick("roast", CHAT_ID) == "يعني انتي بتلحسي خرى للعيال"


def test_pick_no_fitting_line_returns_none():
    # Degenerate pool: every line is target-specific and none fits.
    # The bank must serve NOTHING rather than a non-sequitur.
    rb._bank_cache = {"roast": [
        {"id": "ro-y", "line": "السيسي ده حيوان", "trigger": "roast",
         "target": "السيسي"},
    ]}
    rb._last_used.clear()
    assert _pick("roast", CHAT_ID, target="صلاح") is None
    assert _pick("roast", CHAT_ID, target="السيسي") == "السيسي ده حيوان"


# --- the live bug, exact case -------------------------------------------------

def test_bug_case_salah_never_gets_quran_line():
    # Exact live message: "اشتم صلاح" (صلاح is not a group member).
    for member_state in (False, True, None):
        seen = _draws("اشتم صلاح", 100, target_is_member=member_state)
        assert seen, "roast must still answer for صلاح"
        assert QURAN_LINE not in seen
        assert not any("القرآن" in line for line in seen)
        assert seen <= _generic_lines()


def test_salah_gets_generic_only():
    generic = _generic_lines()
    assert len(generic) == 20  # 11 transcript + 9 user-submitted
    for text in ("اشتم صلاح", "يا بهجت اشتم صلاح"):
        seen = _draws(text, 60, target_is_member=False)
        assert seen <= generic
        assert not any("السيسي" in line for line in seen)


def test_sisi_line_never_fires_for_other_targets():
    sisi = _subject_lines("السيسي")
    assert QURAN_LINE in sisi and SISI_LINE in sisi
    for target in ("صلاح", "محمد", "مروان", "أحمد", "علي"):
        seen = _draws(f"اشتم {target}", 60, target_is_member=False)
        assert not (seen & sisi), target
        assert not any("السيسي" in line for line in seen), target
        assert not any("القرآن" in line for line in seen), target


# --- Sisi targets still get Sisi lines ----------------------------------------

def test_sisi_may_get_sisi_lines():
    sisi = _subject_lines("السيسي")
    seen = _draws("اشتم السيسي", 100, target_is_member=False)
    assert seen & sisi, "Sisi-specific lines must stay reachable for السيسي"
    assert QURAN_LINE in seen
    assert SISI_LINE in seen
    assert seen <= _generic_lines() | sisi


def test_sisi_alias_variants_reach_sisi_lines():
    sisi = _subject_lines("السيسي")
    for text in ("اشتم سيسي", "اشتم بلحة"):
        seen = _draws(text, 80, target_is_member=False)
        assert seen & sisi, text
        assert seen <= _generic_lines() | sisi


def test_other_subjects_reach_their_lines():
    assert _draws("اشتم كيسنجر", 80, target_is_member=False) & (
        _subject_lines("كيسنجر"))
    assert _draws("اشتم لينا", 80, target_is_member=False) & (
        _subject_lines("لينا"))
    assert _draws("اشتم كارما", 80, target_is_member=False) & (
        _subject_lines("كارما"))
    assert _draws("اشتم الجيش", 80, target_is_member=False) & (
        _subject_lines("الجيش"))


# --- member safety still respected --------------------------------------------

def test_roast_member_target_gets_generic_person_only():
    safe_generic = _generic_lines(member_safe_only=True)
    assert len(safe_generic) == 15  # 20 generic - 5 generic family lines
    for _ in range(60):
        line = match_reply_bank(
            "يا بهجت اشتم محمد", chat_id=CHAT_ID, target_is_member=True)
        assert line in safe_generic


def test_roast_non_member_salah_may_serve_family_generic():
    generic = _generic_lines()
    family_generic = {
        line for line in generic
        if line in {"يا ولد الوسخة",
                    "البلد بلدنا وهنستردها غصب عن أي ابن دين كلب",
                    "يا ولاد الزنوه احترمو عقولنا",
                    "ابن متناكه و ماشي، مغفل و ماشي ، بتاخد من طيزك يطلع من بقك و ماشي لكن غبي يبن المتناكه كمان",
                    "بعبصو بعض في حته تانيه يا ولاد ال هو مفيش غير الخرابه دي"}
    }
    assert len(family_generic) == 5  # 2 transcript + ro-40, ro-42, ro-44 (user)
    seen = _draws("اشتم صلاح", 80, target_is_member=False)
    assert seen <= generic
    assert seen & family_generic  # family lines reachable for non-members


def test_roast_unresolved_target_fails_safe_and_generic():
    safe_generic = _generic_lines(member_safe_only=True)
    for _ in range(60):
        line = match_reply_bank(
            "يا بهجت اشتم صلاح", chat_id=CHAT_ID, target_is_member=None)
        assert line in safe_generic


# --- owner / bot gates --------------------------------------------------------

def test_roast_never_at_owner_or_bot():
    assert match_reply_bank(
        "يا بهجت اشتم سيف", chat_id=CHAT_ID,
        target_is_member=True, target_is_owner=True) is None
    assert match_reply_bank(
        "يا بهجت اشتم السيسي", chat_id=CHAT_ID,
        target_is_member=False, target_is_owner=True) is None
    assert match_reply_bank(
        "اشتم بهجت", chat_id=CHAT_ID, target_is_member=False) is None


# --- other categories unaffected ----------------------------------------------

def test_insulted_branch_still_untargeted():
    # The insulted comeback path takes no target filter: insulting the
    # bot still gets a comeback from the insulted pool.
    insulted = _lines(load_bank()["insulted"])
    seen = {
        match_reply_bank("يا بهجت انت حمار", chat_id=CHAT_ID)
        for _ in range(30)
    } - {None}
    assert seen and seen <= insulted
