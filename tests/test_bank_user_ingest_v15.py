"""v1.5 user-submitted ingest round 2: Seif added 9 more insult lines
on the "قاموس شتايم بهجت" page (2026-11-26), bringing the page total
to 33 (24 round 1 + 9 round 2). All 9 were banked (8 insulted
comebacks in-33..in-40, 1 generic roast ro-41); none dropped — all 9
are insults, none one-word, none near-duplicates of existing lines.
All 9 are member-safe (no family line this round). Owner-authored
lines (confidence "user", source "user-submitted") are served like
verbatim/cleaned; they are never presented as Bahgat transcript lines.
Caveat: in-38 is feminine-addressed ("انتي... يا وليه") and is served
at whoever insults the bot — gender gating is out of scope (same as
ro-23), flagged here only so the choice stays visible.
"""
from pathlib import Path

import pytest
import yaml

from brain.reply_bank import load_bank, match_reply_bank, reload_bank

CHAT_ID = -1005812444791

# The 9 lines Seif added in round 2 (page order, oldest first).
NEW_SUBMITTED = [
    "بطلب منك ممكن انيك حضرتك",
    "ايه الشرمطه دي",
    "انتا ياض خول يالا ، انتا ياض خول ما تخلي عندك شخصيه",
    "اخرررررص اخررررررص يا كس الكلب",
    "رد يالااااااااا رد يالا زي الجاموس",
    "اهلا اهلا ب المنايك اهلا اهلا مرحب مرحب مرحب بيكو",
    "انتي ست متربيتيش عيب احترمي نفسك ، احتررررمي نفسك يا وليه احترمي نفسك يا وليه",
    "دي اسمها شرمطه دي يا استاذ الحالة الانتا فيها دي اسمها شرمطه و منيكه",
    "ده انا زوبرجي من صغري يا بيبي",
]

NEW_INSULTED = NEW_SUBMITTED[:5] + NEW_SUBMITTED[6:]
NEW_ROAST = ["اهلا اهلا ب المنايك اهلا اهلا مرحب مرحب مرحب بيكو"]

# Round-1 dropped lines stay out (unchanged by round 2).
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


def test_round2_lines_all_banked_with_ids():
    raw = _raw()
    banked_lines = {e["line"] for e in raw}
    for ln in NEW_SUBMITTED:
        assert ln in banked_lines, ln
    for ln in STILL_DROPPED:
        assert ln not in banked_lines, ln
    assert len(NEW_SUBMITTED) == 9
    user = [e for e in raw if e.get("confidence") == "user"]
    assert len(user) == 40  # 21 round 1 + 9 round 2 + 10 round 3 (v1.6 phase 1)
    by_line = {e["line"]: e for e in user}
    assert {by_line[ln]["id"] for ln in NEW_INSULTED} == {
        f"in-{i:02d}" for i in range(33, 41)
    }
    assert by_line[NEW_ROAST[0]]["id"] == "ro-41"
    assert by_line[NEW_ROAST[0]]["trigger"] == "roast"


def test_round2_lines_honest_attribution_and_tags():
    raw = _raw()
    user = [e for e in raw if e.get("confidence") == "user"]
    new = [e for e in user if e["line"] in NEW_SUBMITTED]
    assert len(new) == 9
    for e in new:
        assert e["source"] == "user-submitted"
        assert e.get("member_safe") in (True, False)
    # No family line this round: every new line is member-safe.
    assert all(e["member_safe"] is True for e in new)
    # The family detector must agree — none of the 9 is flagged.
    from core.rules import contains_family_insult
    assert not [e["line"] for e in new
                if contains_family_insult(e["line"])]
    # The new roast is generic (no target:) so it fits any roast target.
    assert new and all(
        e.get("target") is None
        for e in new if e["trigger"] == "roast")


def test_round2_insulted_pool_counts():
    bank = load_bank()
    assert len(bank["insulted"]) == 45  # v1.16: in-46 added
    user_insulted = [e for e in bank["insulted"]
                     if e.get("confidence") == "user"]
    assert len(user_insulted) == 30  # 17 round 1 + 8 round 2 + 5 round 3
    assert all(e.get("member_safe") is True for e in user_insulted)


def test_round2_roast_reachable_for_any_target():
    bank = load_bank()
    assert len(bank["roast"]) == 46  # v1.16: ro-47 added
    user_roast = [e for e in bank["roast"]
                  if e.get("confidence") == "user"]
    assert len(user_roast) == 10  # 4 round 1 + 1 round 2 + 5 round 3
    generic = {e["line"] for e in bank["roast"]
               if e.get("target") is None}
    assert len(generic) == 20  # v1.16: ro-47 added  # v1.13: ro-39 targets كريستيانو
    assert NEW_ROAST[0] in generic
    for text in ("اشتم صلاح", "يا بهجت اشتم صلاح"):
        seen = {
            match_reply_bank(text, chat_id=CHAT_ID, target_is_member=False)
            for _ in range(60)
        } - {None}
        assert seen <= generic


def test_round2_no_duplicates():
    raw = _raw()
    lines = [e["line"] for e in raw]
    assert len(lines) == len(set(lines))
    assert len(raw) == 241  # v1.16: +17 study lines
    user_lines = [e["line"] for e in raw
                  if e.get("confidence") == "user"]
    assert len(user_lines) == len(set(user_lines)) == 40
    # Feminine-addressed comeback is banked deliberately (see module
    # docstring); its wording is recorded, not silently dropped.
    assert ("انتي ست متربيتيش عيب احترمي نفسك ، احتررررمي نفسك يا وليه "
            "احترمي نفسك يا وليه") in user_lines
