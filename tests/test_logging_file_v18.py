"""File logging to the /app/data volume (v1.8).

Cloady free tier shows no runtime logs, so handler errors and
per-attempt download outcomes must land in data/bot.log
(RotatingFileHandler, 1 MB x 3 backups) — otherwise a live failure
like the 2026-11-27 silence cannot be diagnosed at all. The file
handler sits on the ROOT logger, so every module logger
(tools.youtube per-attempt warnings, tg.handlers errors) lands there.
"""
import logging
from logging.handlers import RotatingFileHandler
from types import SimpleNamespace

import pytest

import main as main_module


@pytest.fixture
def _cleanup_handlers():
    yield
    root = logging.getLogger()
    for h in list(root.handlers):
        if isinstance(h, RotatingFileHandler):
            root.removeHandler(h)
            try:
                h.close()
            except Exception:
                pass


def _handlers_for(path):
    return [h for h in logging.getLogger().handlers
            if isinstance(h, RotatingFileHandler)
            and getattr(h, "baseFilename", None) == str(path)]


def test_file_handler_captures_module_logs(tmp_path, _cleanup_handlers):
    """A per-attempt download warning and a handler error both land
    in the log file, in the same format as stdout."""
    path = tmp_path / "bot.log"
    main_module._configure_logging(SimpleNamespace(log_level="INFO"),
                                   log_path=path)
    logging.getLogger("tools.youtube").warning(
        "youtube download attempt %s failed: %s", "android",
        "yt-dlp failed: Sign in to confirm you're not a bot.")
    logging.getLogger("tg.handlers").error("handler failed: %s", "boom")
    for h in _handlers_for(path):
        h.flush()
    text = path.read_text(encoding="utf-8")
    assert "tools.youtube WARNING" in text
    assert "youtube download attempt android failed" in text
    assert "tg.handlers ERROR" in text
    assert "handler failed: boom" in text


def test_rotation_is_bounded(tmp_path, _cleanup_handlers):
    """1 MB per file, 3 backups — the volume can never fill with logs."""
    path = tmp_path / "bot.log"
    main_module._configure_logging(SimpleNamespace(log_level="INFO"),
                                   log_path=path)
    handlers = _handlers_for(path)
    assert len(handlers) == 1
    assert handlers[0].maxBytes == 1_000_000
    assert handlers[0].backupCount == 3


def test_second_configure_call_does_not_duplicate(tmp_path,
                                                  _cleanup_handlers):
    """Re-configuring (e.g. a restart in-process) adds no second
    handler for the same file — no duplicated log lines."""
    path = tmp_path / "bot.log"
    main_module._configure_logging(SimpleNamespace(log_level="INFO"),
                                   log_path=path)
    main_module._configure_logging(SimpleNamespace(log_level="INFO"),
                                   log_path=path)
    assert len(_handlers_for(path)) == 1


def test_unwritable_log_path_falls_back_to_console(tmp_path,
                                                   _cleanup_handlers):
    """A volume that cannot be written must never crash the bot:
    configure succeeds, no file handler is added, console keeps
    working."""
    blocker = tmp_path / "not-a-dir"
    blocker.write_text("x")
    main_module._configure_logging(
        SimpleNamespace(log_level="INFO"),
        log_path=blocker / "bot.log")
    assert _handlers_for(blocker / "bot.log") == []
