"""Telegram wiring only."""
import asyncio
import json
import logging
import time
from pathlib import Path

import yaml
from telegram.ext import Application

from core.config import Settings, data_dir
from tg.handlers import _init_db, _prune_processed_updates, register_handlers

logger = logging.getLogger("bahgat")
ROOT = Path(__file__).resolve().parents[1]
# Resolved once at import from BAHGAT_DATA_DIR (default <project root>/data).
DATA_DIR = data_dir()
HEARTBEAT_PATH = DATA_DIR / "heartbeat.json"


def _sweep_old_files(directory: Path, max_age_seconds: int = 3600) -> None:
    """Delete download/voice files older than 1h (leaked by crashes/kills)."""
    if not directory.exists():
        return
    now = time.time()
    for path in directory.rglob("*"):
        try:
            if path.is_file() and now - path.stat().st_mtime > max_age_seconds:
                path.unlink()
        except Exception:
            pass
    # Remove now-empty subfolders.
    for path in sorted(directory.rglob("*"), reverse=True):
        try:
            if path.is_dir() and not any(path.iterdir()):
                path.rmdir()
        except Exception:
            pass


async def _heartbeat_loop(app: Application):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    while True:
        payload = {
            "last_poll": time.time(),
            "last_reply": app.bot_data.get("last_reply_ts"),
        }
        try:
            HEARTBEAT_PATH.write_text(json.dumps(payload), encoding="utf-8")
        except Exception as e:
            logger.warning("heartbeat write failed: %s", e)
        await asyncio.sleep(60)


async def post_init(app: Application):
    settings: Settings = app.bot_data["settings"]
    _init_db()
    _prune_processed_updates(hours=48)
    _sweep_old_files(DATA_DIR / "downloads")
    _sweep_old_files(DATA_DIR / "voice")

    # Parody label on the live bot (Telegram ToS: no impersonation).
    bio = None
    try:
        rules_path = ROOT / "config" / "rules.yaml"
        rules = yaml.safe_load(rules_path.read_text(encoding="utf-8")) or {}
        bio = rules.get("bot_bio_must_say")
    except Exception as e:
        logger.warning("could not read rules.yaml bio: %s", e)
    if bio:
        try:
            await app.bot.set_my_description(bio)
            await app.bot.set_my_short_description(bio)
        except Exception as e:
            logger.warning("setMyDescription failed: %s", e)
    else:
        logger.warning("bot_bio_must_say missing from rules.yaml — parody bio not set")

    if not settings.allowed_chat_ids_set():
        logger.warning(
            "ALLOWED_CHAT_IDS is empty — bot will answer in ANY group it is added to. "
            "Set ALLOWED_CHAT_IDS to the test group id once known (see docs/DEPLOY.md)."
        )
    try:
        me = await app.bot.get_me()
        if not me.can_read_all_group_messages:
            logger.warning(
                "Bot privacy mode is ON (can_read_all_group_messages=false): plain "
                "'بهجت' messages are only delivered if the bot is a group admin or "
                "privacy mode is disabled in BotFather."
            )
    except Exception as e:
        logger.warning("getMe check failed: %s", e)

    app.bot_data["heartbeat_task"] = asyncio.create_task(_heartbeat_loop(app))


async def _post_shutdown(app: Application):
    task = app.bot_data.get("heartbeat_task")
    if task is not None:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
    router = app.bot_data.get("router")
    if router is not None:
        try:
            await router.close()
        except Exception as e:
            logger.warning("router close failed: %s", e)
    # Best-effort WAL checkpoint so the DB is consistent on disk at shutdown.
    try:
        import sqlite3

        db = DATA_DIR / "bahgat.db"
        if db.exists():
            c = sqlite3.connect(db, timeout=10)
            try:
                c.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                c.commit()
            finally:
                c.close()
    except Exception as e:
        logger.warning("wal_checkpoint failed: %s", e)


async def _error_handler(update, context):
    # Log only — never send a message to the group from the error handler.
    logger.exception("handler error: %s", context.error)


def build_application(settings: Settings) -> Application:
    app = (
        Application.builder()
        .token(settings.telegram_bot_token)
        .post_init(post_init)
        .post_shutdown(_post_shutdown)
        .build()
    )
    register_handlers(app, settings)
    app.add_error_handler(_error_handler)
    return app
