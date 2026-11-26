"""v1.4 user-submitted ingest: Seif wrote 24 insult lines on the
"قاموس شتايم بهجت" page (2026-11-26). 21 were banked (17 insulted
comebacks in-16..in-32, 4 generic roasts ro-37..ro-40); 3 were dropped
(two non-insults, one single-word exclamation that duplicates in-30's
"مصمص" and breaks the bank's no-one-word-padding rule). Owner-authored
lines (confidence "user", source "user-submitted") are served like
verbatim/cleaned; they are never presented as Bahgat transcript lines.
Targeting tags are enforced: member-safe lines are person-only, the
one outsiders-only family line (ro-40) never serves at a group member.

Round 2 (v1.5, same day): Seif added 9 more lines on the page; all 9
were banked (8 insulted comebacks in-33..in-40, 1 generic roast ro-41),
so the aggregate counts in this file moved (user 21 -> 30, insulted
served 31 -> 39, roast served 39 -> 40, generic roast 15 -> 16). The
round-1 accounting below (SUBMITTED = 24, BANKED = 21) is unchanged.
"""
from pathlib import Path

import pytest
import yaml

from brain import reply_bank as rb
from brain.reply_bank import load_bank, match_reply_bank, reload_bank

CHAT_ID = -1005812444791

# All 24 lines Seif submitted on the page (page order, oldest first).
SUBMITTED = [
    "انيكها و انتا ماسكها",
    "احترم نفسك بدل ما اركبك يخول بلدك",
    "زبي مانجو متيجي تعالجو",
    "يخووووول انيك انتا و الاقرع العرص",
    "يا اقرررع",
    "حاسس ان زوبي نار",
    "يا سالب يا مبعر احترم رجولتك حتي",
    "يخي بزعل علي الشباب",
    "بص هتجيب زبي و تغرقه كاتشب و مايونيز و تمصمص يسالب",
    "كنت بموت في عنيك كنت بحبك نيك",
    "قووم يا مصري مش هنتحايل عليك",
    "يا كس الكلبه هوهو بعيد",
    "يا ولاد الزنوه احترمو عقولنا",
    "زبي مليان و علي طيزك هيجان",
    "اخرس اخرس يا مزني يا عرص",
    "هركبك و الف بيك مصر كلها يخول",
    "يا نفسي انيكك بس انا محترم",
    "عارف كرستيانو؟ انا زبيانو يا يا منيك لف و صدرها",
    "يا حبيبي يا مصر يا مصر يا حبيبتي يا مصر يا مصر",
    "مصممممممص",
    "هزها و غور ياض اتفو علي دي اشكال",
    "مصمص بعيد صدعتنا",
    "لولا اني محترم كنت ركبتك ركوب البعير",
    "يا الللله منك لله",
]

# The three dropped lines: not insults, so they must NOT be in the bank.
DROPPED = {
    "يا حبيبي يا مصر يا مصر يا حبيبتي يا مصر يا مصر",
    "قووم يا مصري مش هنتحايل عليك",
}
# Dropped for a different reason: a single-word exclamation — the bank's
# no-one-word-padding rule (see test_savagery_v13) — and it duplicates
# in-30's "مصمص بعيد صدعتنا".
DROPPED_SINGLE_WORD = {"مصممممممص"}

BANKED = [ln for ln in SUBMITTED
          if ln not in DROPPED and ln not in DROPPED_SINGLE_WORD]

FAMILY_LINE = "يا ولاد الزنوه احترمو عقولنا"


@pytest.fixture(autouse=True)
def _reset_bank_state():
    reload_bank()
    yield
    reload_bank()


def _raw():
    return yaml.safe_load(open(
        Path(__file__).resolve().parents[1] / "persona/bahgat/reply_bank.yaml",
        encoding="utf-8"))["entries"]


def test_all_submitted_lines_accounted_for():
    raw = _raw()
    banked_lines = {e["line"] for e in raw}
    for ln in BANKED:
        assert ln in banked_lines, ln
    for ln in DROPPED | DROPPED_SINGLE_WORD:
        assert ln not in banked_lines, ln
    assert len(SUBMITTED) == 24
    assert len(BANKED) == 21
    assert len(DROPPED) == 2
    assert len(DROPPED_SINGLE_WORD) == 1


def test_user_lines_honest_attribution_and_ids():
    raw = _raw()
    user = [e for e in raw if e.get("confidence") == "user"]
    assert len(user) == 30  # 21 round 1 + 9 round 2 (v1.5)
    assert set(BANKED) <= {e["line"] for e in user}
    for e in user:
        assert e["source"] == "user-submitted"
        # Explicit member_safe tag on every user line (never an omission).
        assert e.get("member_safe") in (True, False)
    assert {e["id"] for e in user if e["trigger"] == "insulted"} == {
        f"in-{i:02d}" for i in range(16, 41)
    }
    assert {e["id"] for e in user if e["trigger"] == "roast"} == {
        "ro-37", "ro-38", "ro-39", "ro-40", "ro-41",
    }


def test_user_insulted_lines_are_member_safe():
    bank = load_bank()
    assert len(bank["insulted"]) == 39
    user_insulted = [e for e in bank["insulted"]
                     if e.get("confidence") == "user"]
    assert len(user_insulted) == 25
    assert all(e.get("member_safe") is True for e in user_insulted)


def test_user_roast_lines_generic_and_tagged():
    bank = load_bank()
    assert len(bank["roast"]) == 40
    user_roast = [e for e in bank["roast"]
                  if e.get("confidence") == "user"]
    assert len(user_roast) == 5
    # Generic (no target:) so they fit any roast target.
    assert all(e.get("target") is None for e in user_roast)
    by_id = {e["id"]: e for e in user_roast}
    assert by_id["ro-40"]["line"] == FAMILY_LINE
    assert by_id["ro-40"]["member_safe"] is False
    for rid in ("ro-37", "ro-38", "ro-39"):
        assert by_id[rid]["member_safe"] is True


def test_family_user_line_never_served_to_members(monkeypatch):
    # The family line must never serve at a member (or unresolved
    # target), but must stay reachable for a resolved non-member.
    # Deterministic check for the member side (choice = last eligible):
    # ro-41 (v1.5) is the last roast entry now and is member-safe, so
    # the member pick is never the family line.
    monkeypatch.setattr(rb.random, "choice", lambda xs: xs[-1])
    assert match_reply_bank(
        "يا بهجت اشتم محمد", chat_id=CHAT_ID,
        target_is_member=True) != FAMILY_LINE
    assert match_reply_bank(
        "يا بهجت اشتم محمد", chat_id=CHAT_ID,
        target_is_member=None) != FAMILY_LINE
    # Non-member reachability: sample many draws; the family line
    # must appear (it is in the non-member pool).
    monkeypatch.undo()
    seen = {
        match_reply_bank(
            "يا بهجت اشتم محمد", chat_id=CHAT_ID,
            target_is_member=False)
        for _ in range(200)
    }
    assert FAMILY_LINE in seen


def test_user_roast_lines_reachable_for_any_target():
    generic = {e["line"] for e in load_bank()["roast"]
               if e.get("target") is None}
    assert len(generic) == 16
    for text in ("اشتم صلاح", "يا بهجت اشتم صلاح"):
        seen = {
            match_reply_bank(text, chat_id=CHAT_ID, target_is_member=False)
            for _ in range(60)
        } - {None}
        assert seen <= generic


def test_user_lines_no_duplicates():
    raw = _raw()
    lines = [e["line"] for e in raw]
    assert len(lines) == len(set(lines))
    user_lines = [e["line"] for e in raw
                  if e.get("confidence") == "user"]
    assert len(user_lines) == len(set(user_lines))
    # The dropped "مصممممممص" stays out; the fuller "مصمص" line stays in.
    assert "مصممممممص" not in user_lines
    assert "مصمص بعيد صدعتنا" in user_lines
