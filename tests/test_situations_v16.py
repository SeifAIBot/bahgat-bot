"""v1.6 phase 2: contextual insult selection — situation tags, detection,
persisted no-repeat window, mood severity.

- Every served insulted/roast line carries `situations:` tags in the YAML
  (taxonomy in brain.intent: INSULTED_SITUATIONS / ROAST_SITUATIONS).
- detect_insult_situation / detect_roast_situation read the situation
  from the incoming message (deterministic keywords, no LLM call).
- _pick() prefers lines tagged with the detected situation, falls back
  to `general` lines, then to any unused line, then (pool exhausted)
  to the least-recently-used line (deterministic).
- The no-repeat window is persisted in bot_state (last 25 per chat +
  last 10 per user), so it survives restarts — the old in-memory last-5
  is still consulted as a union.
- update_mood() takes an optional insult_bump (default 40 = old flat
  bump); the handler passes SITUATION_MOOD_BUMP for the detected
  situation (family attack +60, mild mock +30).

Caveats carried over, not fixed here:
- in-38 is feminine-addressed ("انتي ست... يا وليه") with no gender
  gating — served at whoever insults the bot (same as ro-23).
- The roast `cowardly` situation has NO tagged line yet (no roast in
  the bank fits it) — a cowardly roast falls back to `general` lines.
"""
from pathlib import Path

import pytest
import yaml

from brain import memory, reply_bank as rb
from brain.intent import (
    INSULTED_SITUATIONS,
    ROAST_SITUATIONS,
    detect_insult_situation,
    detect_roast_situation,
)
from brain.mood import SITUATION_MOOD_BUMP, update_mood
from brain.reply_bank import _pick, load_bank, match_reply_bank, reload_bank

CHAT_ID = -1005812444791


@pytest.fixture(autouse=True)
def _tmp_bank_db(monkeypatch, tmp_path):
    """Isolate the persisted bank-rotation window (v1.6 phase 2):
    _pick() records every served line in brain.memory's bot_state, so
    without this the window would leak between tests (and into the
    real data/bahgat.db)."""
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


def _pool(trigger, situation):
    return {e["line"] for e in load_bank()[trigger]
            if situation in (e.get("situations") or [])}


def _generic(trigger):
    return _pool(trigger, "general")


# --- YAML shape ---------------------------------------------------------------

def test_situations_yaml_shape():
    raw = _raw()
    served = [e for e in raw
              if e["trigger"] in ("insulted", "roast")
              and e.get("confidence") != "approximate"]
    assert len(served) == 91  # 45 insulted + 46 roast (v1.16: in-46 + ro-47)
    for e in served:
        tags = e.get("situations")
        assert tags, f"{e['id']} has no situations tag"
        assert isinstance(tags, list) and len(tags) >= 1
        taxonomy = (INSULTED_SITUATIONS if e["trigger"] == "insulted"
                    else ROAST_SITUATIONS)
        for t in tags:
            assert t in taxonomy, f"{e['id']}: unknown situation {t!r}"
    # in-38 stays feminine-addressed with no gender gating (flagged,
    # not fixed — same as ro-23).
    by_id = {e["id"]: e for e in raw}
    assert by_id["in-38"]["line"].startswith("انتي ست")
    assert "dismissed" in by_id["in-38"]["situations"]
    # ro-41 is a plural greeting-style roast — tagged honestly general.
    assert by_id["ro-41"]["situations"] == ["general"]


def test_situations_per_situation_counts():
    # Pinned counts: the taxonomy is grounded in the actual lines, so a
    # future ingest that retags a line must update these deliberately.
    from collections import Counter
    ins = Counter(t for e in _raw() if e["trigger"] == "insulted"
                  for t in e.get("situations") or [])
    ro = Counter(t for e in _raw() if e["trigger"] == "roast"
                 for t in e.get("situations") or [])
    assert dict(ins) == {
        "general": 11, "mocked": 10, "dismissed": 9, "sworn-at": 6,
        "called-dumb": 4, "family-attacked": 4, "repeated-insult": 4,
        "threatened": 3,
    }
    assert dict(ro) == {
        "general": 19, "perv": 14, "stupid-statement": 9,
        "arrogant": 4, "annoying": 2,
    }
    # cowardly has no tagged line yet — it falls back to `general`.
    assert "cowardly" not in ro


# --- detection ----------------------------------------------------------------

_INSULT_CASES = [
    ("ههههه يا بهجت انت حمار", "mocked"),          # laughter outranks the noun
    ("يا بهجت بتتريق عليا يا عم", "mocked"),
    ("يا بهجت انت حمار", "called-dumb"),
    ("يا بهجت يا غبي", "called-dumb"),
    ("يا بهجت يا معرص", "sworn-at"),
    ("يا بهجت يا شرموط", "sworn-at"),
    ("يا بهجت يا ابن الكلب", "family-attacked"),
    ("يا بهجت امك", "family-attacked"),
    ("يا بهجت يا ولاد الكلب", "family-attacked"),
    ("يا بهجت هقتلك", "threatened"),
    ("يا بهجت هقتلك يا حمار", "threatened"),       # threat outranks called-dumb
    ("يا بهجت اخرس", "dismissed"),
    ("يا بهجت انت تافه", "dismissed"),
    ("يا بهجت يا حمار يا حمار", "repeated-insult"),
    ("يا بهجت يا حمار تاني", "repeated-insult"),
    ("يا بهجت يا وسخ", "sworn-at"),
]


def test_detect_insult_situation_cases():
    for text, expected in _INSULT_CASES:
        assert detect_insult_situation(text) == expected, text


def test_detect_insult_situation_friendly_not_family():
    assert detect_insult_situation("يا ابن عمي عامل ايه") == "general"


_ROAST_CASES = [
    ("اشتم محمد", "general"),                       # bare request: no situation
    ("يا بهجت اشتم محمد", "general"),
    ("اشتم محمد عشان بيتباهى", "arrogant"),
    ("اشتم محمد عشان مغرور وشايف نفسه", "arrogant"),
    ("اشتم محمد عشان غبي", "stupid-statement"),
    ("اشتم محمد عشان بيهبد", "stupid-statement"),
    ("اشتم محمد عشان جبان", "cowardly"),
    ("اشتم محمد عشان بيهرب", "cowardly"),
    ("اشتم محمد عشان بيزن", "annoying"),
    ("اشتم محمد عشان رغاي وصدعنا", "annoying"),
    ("اشتم محمد عشان شرموط", "perv"),
    ("اشتم محمد عشان بيتحرش", "perv"),
]


def test_detect_roast_situation_cases():
    for text, expected in _ROAST_CASES:
        assert detect_roast_situation(text) == expected, text


# --- contextual selection -----------------------------------------------------

def test_insulted_selection_prefers_situation():
    # One fresh chat per case, so the no-repeat window cannot interfere.
    cases = [
        ("ههههه يا بهجت انت حمار", "mocked"),
        ("يا بهجت انت حمار", "called-dumb"),
        ("يا بهجت يا معرص", "sworn-at"),
        ("يا بهجت يا ابن الكلب", "family-attacked"),
        ("يا بهجت هقتلك", "threatened"),
        ("يا بهجت اخرس", "dismissed"),
        ("يا بهجت يا حمار يا حمار", "repeated-insult"),
    ]
    for i, (text, situation) in enumerate(cases):
        line = match_reply_bank(text, chat_id=CHAT_ID - i, user_id=7)
        assert line in _pool("insulted", situation), (text, line)
    # "general" (no narrowing): _pick serves any insulted line.
    assert _pick("insulted", CHAT_ID - 99, situation="general") in {
        e["line"] for e in load_bank()["insulted"]}


def test_roast_selection_prefers_situation():
    # Expected pools computed from the bank (generic lines only for
    # صلاح — target-specific lines never fit him).
    def _generic_pool(situation):
        return {e["line"] for e in load_bank()["roast"]
                if e.get("target") is None
                and situation in (e.get("situations") or [])}

    cases = [
        ("اشتم صلاح عشان بيتباهى", "arrogant"),
        ("اشتم صلاح عشان غبي", "stupid-statement"),
        ("اشتم صلاح عشان بيزن", "annoying"),
        ("اشتم صلاح عشان شرموط", "perv"),
    ]
    for i, (text, situation) in enumerate(cases):
        pool = _generic_pool(situation)
        assert pool, situation  # the situation must be populated for صلاح
        line = match_reply_bank(text, chat_id=CHAT_ID - i,
                                target_is_member=False)
        assert line in pool, (text, line)
    # Sisi + stupid: Sisi lines AND the generic stupid line are eligible.
    sisi_stupid = {e["line"] for e in load_bank()["roast"]
                   if "stupid-statement" in (e.get("situations") or [])
                   and (e.get("target") in (None, "السيسي"))}
    line = match_reply_bank("اشتم السيسي عشان غبي", chat_id=CHAT_ID - 50,
                            target_is_member=False)
    assert line in sisi_stupid
    # Target filtering still applies first: a صلاح roast never gets a
    # Sisi line, even when the situation matches one.
    for _ in range(20):
        line = match_reply_bank("اشتم صلاح عشان غبي", chat_id=CHAT_ID - 60,
                                target_is_member=False)
        assert "السيسي" not in (line or "")


def test_roast_cowardly_falls_back_to_general():
    # No roast line carries `cowardly` yet: the fallback is a generic
    # line, never a wrong-situation line served as if it matched.
    for i in range(5):
        line = match_reply_bank("اشتم صلاح عشان جبان",
                                chat_id=CHAT_ID - i, target_is_member=False)
        assert line in _generic("roast"), line


# --- no-repeat window ---------------------------------------------------------

def _synthetic_cache(category, n):
    rb._bank_cache = {category: [
        {"id": f"s-{i:02d}", "line": f"line {i:02d}", "trigger": category}
        for i in range(n)
    ]}
    rb._last_used.clear()


def test_no_repeat_window_25_no_repeat_within_window():
    _synthetic_cache("insulted", 30)
    picks = [_pick("insulted", CHAT_ID) for _ in range(60)]
    assert all(picks)
    for i, p in enumerate(picks):
        assert p not in picks[max(0, i - 25):i], f"repeat at {i}: {p}"
    # The first 25 picks are all distinct by construction (the window
    # only excludes previous picks while it is still filling).
    assert len(set(picks[:25])) == 25
    assert len(set(picks)) >= 25


def test_no_repeat_window_survives_restart():
    # Simulate a restart: the in-memory last-5 is gone, the DB is not.
    _synthetic_cache("insulted", 30)
    first = [_pick("insulted", CHAT_ID) for _ in range(5)]
    assert len(set(first)) == 5
    assert len(memory.get_recent_bank_lines(CHAT_ID, "insulted")) == 5
    rb._last_used.clear()  # process restart loses in-memory state only
    rest = [_pick("insulted", CHAT_ID) for _ in range(5)]
    assert len(set(rest)) == 5
    assert not (set(first) & set(rest)), "persisted window did not survive"
    assert len(memory.get_recent_bank_lines(CHAT_ID, "insulted")) == 10


def test_no_repeat_small_pool_cycles_deterministically():
    # Pool (4) <= window (25): once exhausted, picks cycle in
    # least-recently-used order instead of repeating at random.
    _synthetic_cache("insulted", 4)
    picks = [_pick("insulted", CHAT_ID) for _ in range(8)]
    assert len(set(picks[:4])) == 4
    assert picks[4:] == picks[:4]


def test_per_user_window_blocks_same_person_repeat():
    # User A gets a line; later the CHAT window has slid past it (25
    # other lines served since), but A's own window still holds it —
    # so A never gets the same comeback twice in a row. The in-memory
    # window is cleared to isolate the mechanism: only the persisted
    # per-user window can exclude the line here.
    _synthetic_cache("insulted", 30)
    mine = _pick("insulted", CHAT_ID, user_id=111)
    mine_id = next(e["id"] for e in load_bank()["insulted"]
                   if e["line"] == mine)
    rb._last_used.clear()
    others = [e["id"] for e in load_bank()["insulted"]
              if e["id"] != mine_id][:25]
    for line_id in others:
        memory.record_bank_line(CHAT_ID, "insulted", line_id)
    assert mine_id not in memory.get_recent_bank_lines(CHAT_ID, "insulted")
    assert mine_id in memory.get_recent_bank_lines(CHAT_ID, "insulted", 111)
    again = _pick("insulted", CHAT_ID, user_id=111)
    assert again != mine


# --- safety still holds -------------------------------------------------------

def test_family_attacked_comeback_stays_member_safe():
    # The user attacked the bot's family; the comeback is still a
    # person-only line — the insulted pool never serves family lines.
    for i in range(10):
        line = match_reply_bank("يا بهجت يا ابن الكلب",
                                chat_id=CHAT_ID - i, user_id=7)
        assert line in {e["line"] for e in load_bank()["insulted"]}
        entry = next(e for e in load_bank()["insulted"]
                     if e["line"] == line)
        assert entry.get("member_safe", True) is not False


def test_roast_member_target_still_person_only():
    safe_generic = {e["line"] for e in load_bank()["roast"]
                    if e.get("target") is None
                    and e.get("member_safe", True) is not False}
    for _ in range(30):
        line = match_reply_bank("يا بهجت اشتم محمد عشان بيتباهى",
                                chat_id=CHAT_ID, target_is_member=True)
        assert line in safe_generic


# --- mood severity ------------------------------------------------------------

def test_mood_severity_family_beats_mock():
    assert update_mood(30, True) == 70  # default unchanged (+40)
    assert update_mood(30, True,
                       insult_bump=SITUATION_MOOD_BUMP["family-attacked"]) == 90
    assert update_mood(30, True,
                       insult_bump=SITUATION_MOOD_BUMP["mocked"]) == 60
    assert (SITUATION_MOOD_BUMP["family-attacked"]
            > SITUATION_MOOD_BUMP["mocked"])
    assert SITUATION_MOOD_BUMP["general"] == 40
    # Praise / calm turns are untouched by the new parameter.
    assert update_mood(50, False, True) == 30
    assert update_mood(50, False) == 50
