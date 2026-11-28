"""Reply bank: loading, the v2.0 serving filter, no-repeat window."""
import random

from bahgat import reply_bank, rules

BANK = reply_bank.load_bank()


class TestLoading:
    def test_categories_present(self):
        for cat in ("insulted", "roast", "dismiss", "catchphrase"):
            assert cat in BANK, cat
            assert BANK[cat], cat

    def test_total_reasonable(self):
        assert sum(len(v) for v in BANK.values()) > 200


class TestServingFilter:
    def test_every_member_servable_line_is_clean(self):
        # Default = member (fail-safe): no family lines, no approximate
        # confidence, and no other red-line violation.
        for cat, entries in reply_bank.servable_bank(is_member=True).items():
            for e in entries:
                assert e.get("confidence") != "approximate", e["id"]
                assert e.get("member_safe") is not False, e["id"]
                line = e["line"]
                assert rules.find_violation(line, check_family=True) is None, (e["id"], line)

    def test_non_member_bank_serves_family_lines(self):
        # There ARE family-insult lines in the raw bank; for a resolved
        # non-member they are eligible (owner rule).
        raw_family = [e for entries in BANK.values() for e in entries
                      if rules.contains_family_insult(e.get("line", ""))]
        assert raw_family, "expected the raw bank to contain family lines"
        served = reply_bank.servable_bank(is_member=False)
        served_ids = {e["id"] for entries in served.values() for e in entries}
        assert any(e["id"] in served_ids for e in raw_family)

    def test_family_lines_excluded_for_members(self):
        # The same raw family lines must never serve at a member.
        raw_family = [e for entries in BANK.values() for e in entries
                      if rules.contains_family_insult(e.get("line", ""))]
        assert raw_family, "expected the raw bank to contain family lines"
        served_ids = {e["id"] for entries in reply_bank.servable_bank(is_member=True).values()
                      for e in entries}
        for e in raw_family:
            assert e["id"] not in served_ids, e["id"]

    def test_targeted_lines_served_only_with_target(self, tmp_data):
        # A Sisi-targeted roast line is pickable with the target, never
        # generic (no target = tagged lines never serve).
        e = reply_bank.pick("roast", chat_id=1, is_member=False,
                            target="السيسي", rng=random.Random(0))
        assert e and e.get("target") == "السيسي"
        generic = reply_bank.pick("roast", chat_id=1, is_member=False,
                                  rng=random.Random(0))
        assert generic and not generic.get("target")

    def test_messi_never_picked_as_roast_target(self, tmp_data):
        # Messi is defended, never roasted: no roast line targets him.
        e = reply_bank.pick("roast", chat_id=1, is_member=False,
                            target="ميسي", rng=random.Random(0))
        assert e is None or not reply_bank.is_messi_target(e.get("target") or "")
        # And the handler-level guard agrees:
        assert reply_bank.is_messi_target("ميسي")
        assert not reply_bank.is_messi_target("السيسي")

    def test_enough_lines_remain(self):
        s = reply_bank.servable_bank()
        assert len(s.get("insulted", [])) >= 20
        assert len(s.get("roast", [])) >= 5
        assert len(s.get("dismiss", [])) >= 5


class TestPicking:
    def test_pick_returns_entry(self, tmp_data):
        e = reply_bank.pick("insulted", chat_id=1, rng=random.Random(0))
        assert e and e.get("line")

    def test_no_repeat_within_window(self, tmp_data):
        chat_id = 77
        seen = set()
        n = len(reply_bank.servable_bank()["insulted"])
        for i in range(min(10, n)):
            e = reply_bank.pick("insulted", chat_id=chat_id,
                                rng=random.Random(i))
            assert e["id"] not in seen
            seen.add(e["id"])

    def test_unknown_category_returns_none(self, tmp_data):
        assert reply_bank.pick("no_such_category", chat_id=1) is None

    def test_fallback_lines_exist(self):
        for kind in ("insulted", "roast", "dismiss", "media_fail", "error",
                     "thanks", "greeting"):
            assert reply_bank.fallback_line(kind)
