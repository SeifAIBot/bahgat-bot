"""Bahgat Bot — entry point. Wiring only; logic lives in bahgat/."""
import logging
import os
from logging.handlers import RotatingFileHandler

from bahgat.app import build_application
from bahgat.config import data_dir, load_settings

logger = logging.getLogger("bahgat")

_LOG_MAX_BYTES = 1_000_000
_LOG_BACKUP_COUNT = 3


def _configure_logging(settings) -> None:
    level_name = (settings.log_level or "INFO").upper()
    # Never DEBUG in production: PTB DEBUG logs full request URLs, which
    # contain the bot token. Explicit escape hatch only.
    if level_name == "DEBUG" and os.environ.get("BAHGAT_DEBUG") != "1":
        level_name = "INFO"
    level = getattr(logging, level_name, logging.INFO)
    logging.basicConfig(
        level=level, format="%(asctime)s %(name)s %(levelname)s %(message)s"
    )
    try:
        path = data_dir()
        path.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(
            path / "bot.log", maxBytes=_LOG_MAX_BYTES,
            backupCount=_LOG_BACKUP_COUNT, encoding="utf-8",
        )
        handler.setFormatter(logging.Formatter(
            "%(asctime)s %(name)s %(levelname)s %(message)s"))
        logging.getLogger().addHandler(handler)
    except OSError as e:
        logger.warning("file logging unavailable (%s); console only", e)


def main() -> None:
    settings = load_settings()
    _configure_logging(settings)
    app = build_application(settings)
    logger.info("Bahgat starting — polling")
    app.run_polling(
        timeout=30,
        allowed_updates=["message"],
        drop_pending_updates=settings.drop_pending_updates,
        bootstrap_retries=-1,
    )


if __name__ == "__main__":
    main()
