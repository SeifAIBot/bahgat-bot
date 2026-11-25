"""Shared fixtures for handler tests."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest  # noqa: E402


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
