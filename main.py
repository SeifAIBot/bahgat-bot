"""Bahgat Bot — entry point. Wiring only, no business logic here.
Handlers live in tg/, logic in brain/ + tools/, config in core/.
See docs/ARCHITECTURE.md.

NOTE: the local package is named `tg/`, not `telegram/` — the old `telegram/`
directory shadowed the installed python-telegram-bot package of the same
name, so v0.4 could not even `import telegram.handlers` from the project
root. `from telegram import ...` below always means the installed library.
"""
import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path

from core.config import load_settings
from tg.app import build_application
from tg.health import start_health_server, stop_health_server

logger = logging.getLogger("bahgat")

# v1.8: Cloady free tier shows no runtime (stdout) logs, so handler
# errors and per-attempt download outcomes must land in a file under
# the /app/data volume (the persistent mount) — otherwise a live
# failure like the 2026-11-27 silence cannot be diagnosed at all.
# Bounded: 1 MB per file, 3 backups (~4 MB max), so the volume can
# never fill up with logs.
_LOG_MAX_BYTES = 1_000_000
_LOG_BACKUP_COUNT = 3
_LOG_FILENAME = "bot.log"


def _default_log_path() -> Path:
    return Path(__file__).resolve().parent / "data" / _LOG_FILENAME


def _configure_logging(settings, log_path=None) -> None:
    # Honour settings.log_level, but never DEBUG in production: PTB DEBUG
    # logs full request URLs, which contain the bot token. DEBUG is allowed
    # only with the explicit BAHGAT_DEBUG=1 escape hatch.
    level_name = (settings.log_level or "INFO").upper()
    if level_name == "DEBUG" and os.environ.get("BAHGAT_DEBUG") != "1":
        level_name = "INFO"
    level = getattr(logging, level_name, logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    # File handler on the ROOT logger: captures every module logger
    # (tools.youtube per-attempt warnings, tg.handlers errors) in the
    # same format as stdout. Never crash the bot over logging: an
    # unwritable volume falls back to console-only with a warning.
    # log_path is injectable for tests; production uses data/bot.log
    # under the repo root (/app/data on Cloady — the volume mount).
    try:
        path = (Path(log_path).resolve() if log_path is not None
                else _default_log_path())
        path.parent.mkdir(parents=True, exist_ok=True)
        root = logging.getLogger()
        if not any(
            isinstance(h, RotatingFileHandler)
            and getattr(h, "baseFilename", None) == str(path)
            for h in root.handlers
        ):
            handler = RotatingFileHandler(
                path, maxBytes=_LOG_MAX_BYTES, backupCount=_LOG_BACKUP_COUNT,
                encoding="utf-8",
            )
            handler.setFormatter(logging.Formatter(
                "%(asctime)s %(name)s %(levelname)s %(message)s"))
            handler.setLevel(level)
            root.addHandler(handler)
    except OSError as e:
        logger.warning("file logging unavailable (%s); console only", e)


def main():
    settings = load_settings()
    _configure_logging(settings)
    app = build_application(settings)
    logger.info("Bahgat starting — polling")
    # Health endpoint for PaaS health checks (Northflank /healthz). Daemon
    # thread, stdlib only; stopped in the finally below so a SIGTERM ends
    # it cleanly with the polling loop.
    health_server = start_health_server()
    try:
        # drop_pending_updates defaults True: after downtime the bot must NOT
        # chew through a stale backlog with LLM calls (quota + replies to
        # day-old messages). Set DROP_PENDING_UPDATES=false on a host that
        # sleeps/restarts often (Render free web service / Northflank) so
        # messages sent while the bot was down are delivered on wake instead
        # of discarded.
        # bootstrap_retries=-1 so a brief Telegram outage at boot retries
        # instead of crash-looping.
        app.run_polling(
            timeout=30,
            allowed_updates=["message", "callback_query", "chat_member", "my_chat_member"],
            drop_pending_updates=settings.drop_pending_updates,
            bootstrap_retries=-1,
        )
    finally:
        stop_health_server(health_server)


if __name__ == "__main__":
    main()
