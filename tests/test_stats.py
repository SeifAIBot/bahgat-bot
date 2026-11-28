"""Minimal RED counters (v2.2): record, snapshot, cooldown, reset."""
from bahgat import stats


class TestRecord:
    def test_counts_and_latency(self):
        stats.reset()
        stats.record("groq-20b", "openai/gpt-oss-20b", "ok", 100)
        stats.record("groq-20b", "openai/gpt-oss-20b", "ok", 200)
        stats.record("groq-20b", "openai/gpt-oss-20b", "429", 300)
        p = stats.snapshot()["providers"]["groq-20b"]
        assert p["total"] == 3
        assert p["ok"] == 2
        assert p["success_rate"] == 0.67
        assert p["failures"] == {"429": 1}
        assert p["p50_ms"] == 200
        assert p["p95_ms"] == 300
        assert p["dead"] is False

    def test_fallback_counter(self):
        stats.reset()
        stats.record("groq-20b", "openai/gpt-oss-20b", "429", 50,
                     fallback_to="groq-120b")
        assert stats.snapshot()["fallbacks"] == {"groq-20b->groq-120b": 1}

    def test_bank_fallback_counter(self):
        stats.reset()
        stats.record_bank_fallback("all_providers_down")
        stats.record_bank_fallback("all_providers_down")
        assert stats.snapshot()["bank_fallbacks"] == {"all_providers_down": 2}

    def test_empty_snapshot(self):
        stats.reset()
        assert stats.snapshot() == {"providers": {}, "fallbacks": {},
                                    "bank_fallbacks": {}}


class TestCooldown:
    def test_mark_dead_and_reset(self):
        stats.reset()
        assert not stats.is_dead("groq-20b")
        stats.mark_dead("groq-20b", "429", 600)
        assert stats.is_dead("groq-20b")
        assert stats.snapshot()["providers"] == {}  # dead alone is not a call
        stats.reset()
        assert not stats.is_dead("groq-20b")

    def test_dead_shows_in_snapshot(self):
        stats.reset()
        stats.record("groq-20b", "openai/gpt-oss-20b", "429", 10)
        stats.mark_dead("groq-20b", "429", 600)
        assert stats.snapshot()["providers"]["groq-20b"]["dead"] is True
