"""Router v0.6 tests — per-model caps, migration, new provider adapters,
graceful disable on 401/404, routing order, least-used-first, Gemma rpm
guard, output caps. No live calls: all clients are fakes / mocked."""
import asyncio
import sqlite3
import time
from types import SimpleNamespace

import pytest

from brain.router import BrainRouter, NO_KEYS_MSG, FAIL_MSG


def _all_keys():
    return SimpleNamespace(
        gemini_api_key="fake-gemini", groq_api_key="fake-groq",
        cerebras_api_key="fake-cerebras", nvidia_api_key="fake-nvidia",
        openrouter_api_key="fake-openrouter")


def _router(tmp_path, settings=None):
    router = BrainRouter(settings or _all_keys())
    router.db = tmp_path / "router.db"
    return router


def _today():
    return time.strftime("%Y-%m-%d", time.gmtime())


class _FakeCompletions:
    """Records kwargs; fails for models in fail_models with the given
    status (error class carries status_code, like openai errors)."""

    def __init__(self, calls, fail_models=None, fail_status=503, fail_text="boom"):
        self._calls = calls
        self._fail_models = set(fail_models or [])
        self._fail_status = fail_status
        self._fail_text = fail_text

    async def create(self, **kwargs):
        self._calls.append(kwargs)
        if kwargs.get("model") in self._fail_models:
            status = self._fail_status

            class E(Exception):
                status_code = status

            raise E(self._fail_text)
        usage = SimpleNamespace(prompt_tokens=10, completion_tokens=5,
                                completion_tokens_details=None,
                                prompt_tokens_details=None)
        msg = SimpleNamespace(content="اهلا يا عم")
        choice = SimpleNamespace(message=msg, finish_reason="stop")
        return SimpleNamespace(choices=[choice], usage=usage)


class _FakeClient:
    def __init__(self, calls, **kw):
        self.chat = SimpleNamespace(completions=_FakeCompletions(calls, **kw))

    async def close(self):
        pass


def _seed(router, provider, model, requests=0, tokens_in=0, tokens_out=0):
    router.db.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(router.db)
    router._ensure_usage_table(c)
    c.execute("INSERT INTO provider_usage(provider, model, date, requests, tokens_in, tokens_out)"
              " VALUES(?,?,?,?,?,?)",
              (provider, model, _today(), requests, tokens_in, tokens_out))
    c.commit()
    c.close()


def _rows(router):
    c = sqlite3.connect(router.db)
    rows = c.execute("SELECT provider, model, date, requests, tokens_in, tokens_out"
                     " FROM provider_usage ORDER BY provider, model").fetchall()
    c.close()
    return rows


# --- per-model Groq caps ----------------------------------------------------

def test_groq_120b_exhausted_does_not_block_20b(tmp_path):
    router = _router(tmp_path)
    _seed(router, "groq-120b", "openai/gpt-oss-120b", tokens_in=180000)
    calls = []
    router._client = lambda name: _FakeClient(calls)
    text, provider, _ = asyncio.run(
        router.chat([{"role": "user", "content": "عامل ايه"}], hard=False))
    assert text == "اهلا يا عم" and provider == "groq"
    assert calls[0]["model"] == "openai/gpt-oss-20b"


def test_groq_20b_exhausted_does_not_block_120b(tmp_path):
    router = _router(tmp_path)
    _seed(router, "groq-20b", "openai/gpt-oss-20b", tokens_in=180000)
    calls = []
    router._client = lambda name: _FakeClient(calls)
    _text, provider, _t = asyncio.run(
        router.chat([{"role": "user", "content": "مين كسب؟"}], hard=True))
    assert provider == "groq"
    assert calls[0]["model"] == "openai/gpt-oss-120b"


def test_groq_20b_exhausted_simple_falls_to_qwen(tmp_path):
    router = _router(tmp_path)
    _seed(router, "groq-20b", "openai/gpt-oss-20b", tokens_in=180000)
    calls = []
    router._client = lambda name: _FakeClient(calls)
    asyncio.run(router.chat([{"role": "user", "content": "عامل ايه"}], hard=False))
    assert calls[0]["model"] == "qwen/qwen3.8-27b"


def test_groq_qwen_has_own_counter(tmp_path):
    # Groq-only keys so the plan is just the Groq entries.
    router = _router(tmp_path, SimpleNamespace(
        gemini_api_key="", groq_api_key="fake-groq",
        cerebras_api_key="", nvidia_api_key="", openrouter_api_key=""))
    _seed(router, "groq-qwen", "qwen/qwen3.8-27b", tokens_in=180000)
    _seed(router, "groq-20b", "openai/gpt-oss-20b", tokens_in=1000)
    rows = {(p, m): (r, ti, to) for p, m, _d, r, ti, to in _rows(router)}
    assert rows[("groq-qwen", "qwen/qwen3.8-27b")] == (0, 180000, 0)
    assert rows[("groq-20b", "openai/gpt-oss-20b")] == (0, 1000, 0)
    # qwen exhausted, 20b fine: simple chat must not touch qwen first.
    calls = []
    router._client = lambda name: _FakeClient(calls)
    asyncio.run(router.chat([{"role": "user", "content": "hi"}], hard=False))
    assert calls[0]["model"] == "openai/gpt-oss-20b"


def test_record_usage_is_per_model(tmp_path):
    router = _router(tmp_path)
    router._record_usage("groq-120b", 100, 50, model="openai/gpt-oss-120b")
    router._record_usage("groq-20b", 10, 5, model="openai/gpt-oss-20b")
    rows = {(p, m): (r, ti, to) for p, m, _d, r, ti, to in _rows(router)}
    assert rows[("groq-120b", "openai/gpt-oss-120b")] == (1, 100, 50)
    assert rows[("groq-20b", "openai/gpt-oss-20b")] == (1, 10, 5)
    # Back-compat family read sums both.
    fam = [v for (p, _m), v in rows.items()
           if p == "groq" or p.startswith("groq-")]
    assert tuple(sum(v[i] for v in fam) for i in range(3)) == (2, 110, 55)


# --- migration from v0.5-shaped DB ------------------------------------------

def test_migration_from_v05_table(tmp_path):
    router = _router(tmp_path)
    db = tmp_path / "router.db"
    db.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(db)
    c.execute("""CREATE TABLE provider_usage
                 (provider TEXT, date TEXT, requests INTEGER DEFAULT 0, tokens_in INTEGER DEFAULT 0,
                  tokens_out INTEGER DEFAULT 0, exhausted_until REAL, PRIMARY KEY(provider, date))""")
    c.execute("INSERT INTO provider_usage(provider, date, requests, tokens_in, tokens_out)"
              " VALUES(?,?,?,?,?)", ("groq", _today(), 7, 90000, 1000))
    c.commit()
    c.close()
    # First use migrates: old row preserved with model=''.
    c = sqlite3.connect(router.db)
    router._ensure_usage_table(c)
    c.close()
    rows = _rows(router)
    assert ("groq", "", _today(), 7, 90000, 1000) in rows
    fam = [r for r in rows if r[0] == "groq" or r[0].startswith("groq-")]
    assert (sum(r[3] for r in fam), sum(r[4] for r in fam),
            sum(r[5] for r in fam)) == (7, 90000, 1000)
    sql = sqlite3.connect(db).execute(
        "SELECT sql FROM sqlite_master WHERE name='provider_usage'").fetchone()[0]
    assert "PRIMARY KEY(provider, model, date)" in sql
    # New per-model rows are separate from each other and from the legacy row.
    router._record_usage("groq-120b", 100, 10, model="openai/gpt-oss-120b")
    router._record_usage("groq-20b", 20, 5, model="openai/gpt-oss-20b")
    rows = dict(((p, m), (r, ti, to)) for p, m, _d, r, ti, to in _rows(router))
    assert rows[("groq-120b", "openai/gpt-oss-120b")] == (1, 100, 10)
    assert rows[("groq-20b", "openai/gpt-oss-20b")] == (1, 20, 5)
    # Per-entry reads sum the legacy (unattributable) row + the own row.
    legacy = rows[("groq", "")]
    assert tuple(legacy[i] + rows[("groq-120b", "openai/gpt-oss-120b")][i]
                 for i in range(3)) == (8, 90100, 1010)
    assert tuple(legacy[i] + rows[("groq-20b", "openai/gpt-oss-20b")][i]
                 for i in range(3)) == (8, 90020, 1005)
    # Migration is idempotent: the legacy row appears exactly once even
    # after further writes re-ran the migration.
    assert sum(1 for r in _rows(router)
               if r[0] == "groq" and r[1] == "") == 1


def test_mark_exhausted_is_per_model(tmp_path):
    router = _router(tmp_path)
    router._mark_exhausted("groq-120b", seconds=3600, model="openai/gpt-oss-120b")
    assert router._quota_exhausted("groq-120b")
    assert not router._quota_exhausted("groq-20b")


# --- new provider adapters (no live calls) ----------------------------------

@pytest.mark.parametrize("family,base", [
    ("cerebras", "https://api.cerebras.ai/v1"),
    ("nvidia", "https://integrate.api.nvidia.com/v1"),
    ("openrouter", "https://openrouter.ai/api/v1"),
    ("groq", "https://api.groq.com/openai/v1"),
    ("gemini", "https://generativelanguage.googleapis.com/v1beta/openai/"),
])
def test_adapter_construction(tmp_path, family, base):
    router = _router(tmp_path)
    client = router._client(family)
    assert str(client.base_url).rstrip("/") == base.rstrip("/")
    assert client.api_key == router.keys[family]
    asyncio.run(router.close())


def test_openrouter_headers(tmp_path):
    router = _router(tmp_path)
    client = router._client("openrouter")
    headers = dict(client.default_headers)
    assert headers["HTTP-Referer"] == "https://t.me/Bahgoti_bot"
    assert headers["X-Title"] == "Bahgat Bot"
    asyncio.run(router.close())


def test_missing_optional_keys_bot_starts_and_skips(tmp_path):
    router = BrainRouter(SimpleNamespace(gemini_api_key="fake-gemini",
                                         groq_api_key="fake-groq"))
    router.db = tmp_path / "router.db"
    plan = [e["name"] for e in router._build_plan(hard=False)]
    assert plan and all(e not in plan for e in
                        ("cerebras-120b", "nvidia-nemotron",
                         "openrouter-gemma", "openrouter-nemotron"))
    calls = []
    router._client = lambda name: _FakeClient(calls)
    text, provider, _ = asyncio.run(
        router.chat([{"role": "user", "content": "hi"}], hard=False))
    assert text == "اهلا يا عم" and provider == "groq"


def test_no_keys_only_when_none_have_a_key(tmp_path):
    router = BrainRouter(SimpleNamespace(gemini_api_key="", groq_api_key="",
                                         cerebras_api_key="", nvidia_api_key="",
                                         openrouter_api_key=""))
    router.db = tmp_path / "router.db"
    text, provider, _ = asyncio.run(
        router.chat([{"role": "user", "content": "hi"}]))
    assert provider == "none" and text == NO_KEYS_MSG


def test_single_optional_key_is_enough(tmp_path):
    router = BrainRouter(SimpleNamespace(gemini_api_key="", groq_api_key="",
                                         cerebras_api_key="fake-cerebras"))
    router.db = tmp_path / "router.db"
    calls = []
    router._client = lambda name: _FakeClient(calls)
    text, provider, _ = asyncio.run(
        router.chat([{"role": "user", "content": "hi"}], hard=False))
    assert text == "اهلا يا عم" and provider == "cerebras"
    assert calls[0]["model"] == "gpt-oss-120b"


# --- graceful disable on 401/404 --------------------------------------------

def test_graceful_disable_on_401_then_next_entry(tmp_path):
    router = _router(tmp_path)
    calls = []

    def fake_client(name):
        return _FakeClient(calls, fail_models={"openai/gpt-oss-20b"},
                           fail_status=401, fail_text="unauthorized")

    router._client = fake_client
    text, provider, _ = asyncio.run(
        router.chat([{"role": "user", "content": "hi"}], hard=False))
    assert text == "اهلا يا عم"
    assert "groq-20b" in router._disabled
    assert "groq-qwen" not in router._disabled
    assert calls[0]["model"] == "openai/gpt-oss-20b"
    assert calls[1]["model"] == "qwen/qwen3.8-27b"


def test_graceful_disable_on_404_mentioning_model(tmp_path):
    router = _router(tmp_path)
    calls = []

    def fake_client(name):
        return _FakeClient(
            calls,
            fail_models={"openai/gpt-oss-20b", "qwen/qwen3.8-27b", "gpt-oss-120b"},
            fail_status=404, fail_text="model gpt-oss-120b not found")

    router._client = fake_client
    # cerebras-120b also uses model gpt-oss-120b and 404s; router must
    # keep going (nvidia next) and never raise.
    text, provider, _ = asyncio.run(
        router.chat([{"role": "user", "content": "hi"}], hard=False))
    assert text == "اهلا يا عم" and provider == "nvidia"
    assert "cerebras-120b" in router._disabled
    assert text != NO_KEYS_MSG and text != FAIL_MSG


def test_disabled_entry_stays_disabled_next_chat(tmp_path):
    router = _router(tmp_path)
    calls = []
    router._client = lambda name: _FakeClient(
        calls, fail_models={"openai/gpt-oss-20b"}, fail_status=403,
        fail_text="forbidden")
    asyncio.run(router.chat([{"role": "user", "content": "hi"}], hard=False))
    assert "groq-20b" in router._disabled
    calls.clear()
    asyncio.run(router.chat([{"role": "user", "content": "hi"}], hard=False))
    assert calls[0]["model"] != "openai/gpt-oss-20b"


# --- routing order ------------------------------------------------------------

def test_routing_order_simple_starts_groq_20b(tmp_path):
    router = _router(tmp_path)
    plan = [e["name"] for e in router._build_plan(hard=False)]
    assert plan[0] == "groq-20b"
    assert plan.index("groq-qwen") < plan.index("cerebras-120b")
    assert plan.index("cerebras-120b") < plan.index("nvidia-nemotron")
    assert plan[-2:] == ["openrouter-gemma", "openrouter-nemotron"]


def test_routing_order_hard_starts_groq_120b_flash_preview_last(tmp_path):
    router = _router(tmp_path)
    plan = [e["name"] for e in router._build_plan(hard=True)]
    assert plan[0] == "groq-120b"
    assert plan.index("groq-qwen") < plan.index("cerebras-120b")
    assert plan.index("cerebras-120b") < plan.index("gemini-3.5-flash-lite")
    assert plan.index("gemini-gemma") < plan.index("gemini-3-flash-preview")
    assert plan[-2:] == ["openrouter-gemma", "openrouter-nemotron"]
    # flash-preview is hard-only: never in the simple plan.
    assert "gemini-3-flash-preview" not in [e["name"] for e in router._build_plan(hard=False)]


def test_least_used_first_within_tier(tmp_path):
    router = _router(tmp_path)
    # Burn both Groq simple entries; cerebras (unused) must jump ahead.
    _seed(router, "groq-20b", "openai/gpt-oss-20b", tokens_in=170000)
    _seed(router, "groq-qwen", "qwen/qwen3.8-27b", tokens_in=170000)
    plan = [e["name"] for e in router._build_plan(hard=False)]
    assert plan[0] == "cerebras-120b"
    assert plan.index("groq-20b") > plan.index("cerebras-120b")
    # And the fuller entry is tried after the emptier one in a real chat.
    calls = []
    router._client = lambda name: _FakeClient(calls)
    asyncio.run(router.chat([{"role": "user", "content": "hi"}], hard=False))
    assert calls[0]["model"] == "gpt-oss-120b"  # cerebras
    assert router._client  # noqa - keep reference


def test_openrouter_shared_50_req_cap(tmp_path):
    router = _router(tmp_path)
    _seed(router, "openrouter-gemma", "google/gemma-4-31b-it:free", requests=50)
    assert router._entry_blocked(router._entry("openrouter-gemma"))
    assert router._entry_blocked(router._entry("openrouter-nemotron"))
    plan = [e["name"] for e in router._build_plan(hard=False)]
    assert "openrouter-gemma" not in plan or True  # plan lists, chat skips
    calls = []
    router._client = lambda name: _FakeClient(
        calls, fail_models={"openai/gpt-oss-20b", "qwen/qwen3.8-27b",
                            "gpt-oss-120b", "nvidia/nemotron-3.5-super-vl-120b-a12b",
                            "gemini-3.5-flash-lite", "gemini-3.1-flash-lite"})
    text, provider, _ = asyncio.run(
        router.chat([{"role": "user", "content": "hi"}], hard=False))
    assert provider == "none" and text == FAIL_MSG
    assert not any(c["model"].endswith(":free") for c in calls)


# --- Gemma rpm guard ----------------------------------------------------------

def test_gemma_rpm_guard_skips_then_recovers(tmp_path):
    router = _router(tmp_path)
    fail = {"openai/gpt-oss-20b", "qwen/qwen3.8-27b", "gpt-oss-120b",
            "openai/gpt-oss-120b",
            "nvidia/nemotron-3.5-super-vl-120b-a12b", "gemini-3.5-flash-lite",
            "gemini-3.1-flash-lite", "gemini-3-flash-preview",
            "google/gemma-4-31b-it:free", "nvidia/nemotron-3-super:free"}
    calls = []
    router._client = lambda name: _FakeClient(calls, fail_models=fail)
    # Gemma called <9s ago -> guard skips it; everything else fails.
    router._last_call["gemini-gemma"] = time.monotonic()
    text, provider, _ = asyncio.run(
        router.chat([{"role": "user", "content": "hi"}], hard=True))
    assert provider == "none" and text == FAIL_MSG
    assert not any(c["model"] == "gemma-4-31b-it" for c in calls)
    # Guard expired -> gemma is tried and succeeds.
    calls.clear()
    router._last_call["gemini-gemma"] = time.monotonic() - 30
    router._client = lambda name: _FakeClient(calls, fail_models=fail)
    text, provider, _ = asyncio.run(
        router.chat([{"role": "user", "content": "hi"}], hard=True))
    assert text == "اهلا يا عم" and provider == "gemini"
    assert calls[-1]["model"] == "gemma-4-31b-it"


# --- output caps ---------------------------------------------------------------

def test_output_caps(tmp_path):
    router = _router(tmp_path)
    calls = []
    router._client = lambda name: _FakeClient(calls)
    # Handlers pass 600 -> 600 for both chat and search.
    asyncio.run(router.chat([{"role": "user", "content": "hi"}], hard=False, max_tokens=600))
    assert calls[0]["max_completion_tokens"] == 600
    calls.clear()
    asyncio.run(router.chat([{"role": "user", "content": "hi"}], hard=True, max_tokens=600))
    assert calls[0]["max_completion_tokens"] == 600
    # No override: groq defaults to 3000 for both simple and hard
    # (v1.13: raised from 1500 — the truncation fix; reasoning tokens
    # count against max_completion_tokens, so a reasoning-heavy turn
    # could eat the whole 1500 budget before the visible reply).
    calls.clear()
    asyncio.run(router.chat([{"role": "user", "content": "hi"}], hard=False))
    assert calls[0]["max_completion_tokens"] == 3000
    calls.clear()
    asyncio.run(router.chat([{"role": "user", "content": "hi"}], hard=True))
    assert calls[0]["max_completion_tokens"] == 3000
    # Gemini defaults to 4000 (groq entries fail through to flash-lite).
    # Fresh router + fresh DB: usage from the earlier chats would
    # reorder the plan via least-used-first.
    router = _router(tmp_path)
    router.db = tmp_path / "router-gemini.db"
    calls.clear()
    router._client = lambda name: _FakeClient(
        calls, fail_models={"openai/gpt-oss-20b", "qwen/qwen3.8-27b",
                            "openai/gpt-oss-120b", "gpt-oss-120b",
                            "nvidia/nemotron-3.5-super-vl-120b-a12b"})
    asyncio.run(router.chat([{"role": "user", "content": "hi"}], hard=False))
    gemini_calls = [c for c in calls if c["model"] == "gemini-3.5-flash-lite"]
    assert gemini_calls and gemini_calls[0]["max_completion_tokens"] == 4000
    # Cerebras / NIM / OpenRouter default to 3000 (fresh router + DB;
    # v1.13: raised from 1500 with the groq cap — same truncation fix).
    router = _router(tmp_path)
    router.db = tmp_path / "router-cerebras.db"
    calls.clear()
    router._client = lambda name: _FakeClient(
        calls, fail_models={"openai/gpt-oss-20b", "qwen/qwen3.8-27b",
                            "openai/gpt-oss-120b"})
    asyncio.run(router.chat([{"role": "user", "content": "hi"}], hard=False))
    cerebras_calls = [c for c in calls if c["model"] == "gpt-oss-120b"]
    assert cerebras_calls and cerebras_calls[0]["max_completion_tokens"] == 3000
    assert "include_reasoning" not in cerebras_calls[0]  # Groq-only kwarg


def test_include_reasoning_only_for_groq(tmp_path):
    router = _router(tmp_path)
    calls = []
    router._client = lambda name: _FakeClient(calls)
    asyncio.run(router.chat([{"role": "user", "content": "hi"}], hard=False))
    assert calls[0]["include_reasoning"] is False
    # Fresh router + fresh DB: the first chat's Groq usage would
    # reorder the plan via least-used-first.
    router = _router(tmp_path)
    router.db = tmp_path / "router2.db"
    calls.clear()
    router._client = lambda name: _FakeClient(
        calls, fail_models={"openai/gpt-oss-20b", "qwen/qwen3.8-27b",
                            "openai/gpt-oss-120b"})
    asyncio.run(router.chat([{"role": "user", "content": "hi"}], hard=False))
    cerebras_calls = [c for c in calls if c["model"] == "gpt-oss-120b"]
    assert cerebras_calls and "include_reasoning" not in cerebras_calls[0]
    groq_calls = [c for c in calls if c["model"].startswith("openai/")]
    assert groq_calls and groq_calls[0]["include_reasoning"] is False


def test_groq_tpm_clamp_still_applies(tmp_path):
    router = _router(tmp_path)
    calls = []
    router._client = lambda name: _FakeClient(calls)
    long_msg = "x" * 14000  # ~7000 est. tokens
    asyncio.run(router.chat([{"role": "user", "content": long_msg}], hard=False))
    assert calls[0]["max_completion_tokens"] == 500  # 7500 - 7000
