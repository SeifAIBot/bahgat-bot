import asyncio
import sqlite3
import time
from types import SimpleNamespace

import pytest

from brain.router import BrainRouter, _classify_429, _seconds_until_midnight_utc


def test_estimate_tokens_arabic():
    assert BrainRouter.estimate_tokens("x" * 100) == 50
    assert BrainRouter.estimate_tokens("") == 1
    assert BrainRouter.estimate_tokens("ab") == 1


def test_classify_429_retry_after_short_is_tpm():
    kind, seconds = _classify_429("rate limited", 30)
    assert kind == "tpm"
    assert seconds == 30


def test_classify_429_daily_quota_is_tpd():
    kind, seconds = _classify_429("daily quota exceeded", None)
    assert kind == "tpd"
    assert 0 < seconds <= 86400
    # Until-midnight: within a minute of the computed value.
    assert abs(seconds - _seconds_until_midnight_utc()) <= 60


def test_classify_429_daily_quota_exception_object():
    kind, _ = _classify_429(Exception("TPD limit: tokens per day exceeded"), None)
    assert kind == "tpd"


def test_classify_429_no_info_is_unknown_60():
    kind, seconds = _classify_429("boom", None)
    assert kind == "unknown"
    assert seconds == 60


def _fake_settings():
    return SimpleNamespace(gemini_api_key="fake-gemini", groq_api_key="fake-groq")


class _FakeCompletions:
    def __init__(self, calls, fail=False):
        self._calls = calls
        self._fail = fail

    async def create(self, **kwargs):
        self._calls.append(kwargs)
        if self._fail:
            class E(Exception):
                status_code = 503
            raise E("service unavailable")
        usage = SimpleNamespace(prompt_tokens=10, completion_tokens=5,
                                completion_tokens_details=None)
        msg = SimpleNamespace(content="اهلا يا عم")
        choice = SimpleNamespace(message=msg, finish_reason="stop")
        return SimpleNamespace(choices=[choice], usage=usage)


class _FakeClient:
    def __init__(self, calls, fail=False):
        self.chat = SimpleNamespace(completions=_FakeCompletions(calls, fail=fail))


def _router_with_tmp_db(tmp_path):
    router = BrainRouter(_fake_settings())
    router.db = tmp_path / "router.db"
    return router


def test_groq_first_simple_chat(tmp_path):
    router = _router_with_tmp_db(tmp_path)
    created, calls = [], []

    def fake_client(name):
        created.append(name)
        return _FakeClient(calls)

    router._client = fake_client
    text, provider, _tokens = asyncio.run(
        router.chat([{"role": "user", "content": "عامل ايه"}], hard=False))
    assert text == "اهلا يا عم"
    assert provider == "groq"
    assert created[0] == "groq"
    assert calls[0]["model"] == "openai/gpt-oss-20b"


def test_hard_chat_tries_groq_120b_first(tmp_path):
    router = _router_with_tmp_db(tmp_path)
    created, calls = [], []

    def fake_client(name):
        created.append(name)
        return _FakeClient(calls)

    router._client = fake_client
    _text, provider, _t = asyncio.run(
        router.chat([{"role": "user", "content": "مين كسب؟"}], hard=True))
    assert provider == "groq"
    assert calls[0]["model"] == "openai/gpt-oss-120b"


def test_gemini_skipped_when_daily_requests_at_cap(tmp_path):
    router = _router_with_tmp_db(tmp_path)
    # v6: caps are per (entry, model). Seed EVERY Gemini entry at its cap
    # so the whole family is skipped: flash-lite 500, gemma 14400,
    # flash-preview 20 (its v0.5 cap was 15 — now 20, last resort).
    router.db.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(router.db)
    c.execute("""CREATE TABLE IF NOT EXISTS provider_usage
                 (provider TEXT, model TEXT DEFAULT '', date TEXT, requests INTEGER DEFAULT 0,
                  tokens_in INTEGER DEFAULT 0, tokens_out INTEGER DEFAULT 0,
                  exhausted_until REAL, PRIMARY KEY(provider, model, date))""")
    today = time.strftime("%Y-%m-%d", time.gmtime())
    for provider, model, reqs in [
            ("gemini-3.5-flash-lite", "gemini-3.5-flash-lite", 500),
            ("gemini-3.1-flash-lite", "gemini-3.1-flash-lite", 500),
            ("gemini-gemma", "gemma-4-31b-it", 14400),
            ("gemini-3-flash-preview", "gemini-3-flash-preview", 20)]:
        c.execute("INSERT INTO provider_usage(provider, model, date, requests) VALUES(?,?,?,?)",
                  (provider, model, today, reqs))
    c.commit()
    c.close()
    created = []

    def fake_client(name):
        created.append(name)
        return _FakeClient([], fail=True)  # groq fails, so router would try gemini next

    router._client = fake_client
    text, provider, _t = asyncio.run(
        router.chat([{"role": "user", "content": "مين كسب؟"}], hard=True))
    assert "gemini" not in created
    assert provider == "none"
    assert text == "الموديلات واقعة دلوقتي، جرب تاني كمان شوية."


def test_no_keys_message(tmp_path):
    router = BrainRouter(SimpleNamespace(gemini_api_key="", groq_api_key=""))
    router.db = tmp_path / "router.db"
    text, provider, _t = asyncio.run(
        router.chat([{"role": "user", "content": "hi"}]))
    assert provider == "none"
    assert text.startswith("يا عم، المفاتيح لسه متظبطتش")
