"""Shared fixtures for handler tests."""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest  # noqa: E402


class WeavingRouter:
    """v1.11 test router: returns a woven reply containing the bank
    ingredient from the system prompt — "والله العظيم يا عم، <line>،
    وكمان كلام من عندي حواليه." The strong lazma keeps voice_check
    quiet, so no regeneration fires and the call count stays 1 per
    turn. Records every call (messages + kwargs). When no ingredient
    is in the prompt, returns a plain acknowledgement."""

    def __init__(self):
        self.calls = []

    async def chat(self, messages, hard=False, temperature=None,
                   max_tokens=None, **kw):
        self.calls.append(messages)
        line = None
        for m in messages:
            content = m.get("content") or ""
            if "[BANK LINE" in content:
                found = re.search(r'السطر: "(.*)"', content)
                if found:
                    line = found.group(1)
        if line:
            return (f"والله العظيم يا عم، {line}، وكمان كلام من عندي حواليه.",
                    "groq", 10)
        return ("تمام يا عم، كلامك وصل.", "groq", 10)


def ingredient_of_call(call_messages):
    """The bank line from a router call's [BANK LINE] block, or None."""
    for m in call_messages:
        content = m.get("content") or ""
        if "[BANK LINE" in content:
            found = re.search(r'السطر: "(.*)"', content)
            if found:
                return found.group(1)
    return None


@pytest.fixture
def tmp_db(monkeypatch, tmp_path):
    """Point handlers' SQLite fallback state at a throwaway DB.

    Also points brain.memory at the same throwaway DB (and re-runs
    init_db, which creates the v0.6 response_cache / hourly_usage tables
    via its migration path) so quota/cache/state touched by handlers never
    leaks into the real data/bahgat.db — and a cached reply stored by one
    test run cannot make a later run take the cache path instead of the
    router. brain.memory's own tests define their own tmp_db fixture.
    """
    import tg.handlers as h
    from brain import memory

    db = tmp_path / "bahgat.db"
    monkeypatch.setattr(h, "DB_PATH", db)
    monkeypatch.setattr(memory, "DB_PATH", db)
    monkeypatch.setattr(memory, "_SCHEMA_DONE", False)
    memory.init_db()
    yield db
    monkeypatch.setattr(memory, "_SCHEMA_DONE", False)


@pytest.fixture(autouse=True)
def _no_human_delay(monkeypatch):
    """v1.9: the mood-based reply pause is real time — zero it for every
    test except the dedicated delay tests (tests/test_mood_delay_v19.py
    re-patches it itself), so the suite stays fast and deterministic."""
    from brain import mood as _mood

    monkeypatch.setattr(_mood, "reply_delay_seconds", lambda mood, text: 0.0)
