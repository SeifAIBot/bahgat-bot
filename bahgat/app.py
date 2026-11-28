"""Application wiring: DB init, LLM client, bot bio, health endpoint."""
import logging

from telegram.ext import Application

from bahgat import db, llm, persona
from bahgat.config import Settings
from bahgat.handlers import register_handlers
from bahgat.health import start_health_server, stop_health_server

logger = logging.getLogger(__name__)


async def post_init(app: Application) -> None:
    db.init_db()
    try:
        app.bot_data["llm"] = llm.LLMClient(app.bot_data["settings"])
    except llm.LLMError as e:
        # The bot still runs: media/search reply, LLM turns get the
        # in-character error line. Logged loudly so the host logs show it.
        logger.error("LLM client could not start: %s", e)
        app.bot_data["llm"] = None

    # The bio labels the account a bot (owner call); in chat he never
    # admits it (owner decision 2026-11-28 — see CHANGELOG for the
    # Telegram §5.2 compliance note).
    try:
        await app.bot.set_my_description(persona.BIO_TEXT)
        await app.bot.set_my_short_description(persona.BIO_TEXT)
    except Exception as e:
        logger.warning("could not set bot description: %s", e)

    settings: Settings = app.bot_data["settings"]
    if not settings.allowed_chat_ids_set():
        logger.warning("ALLOWED_CHAT_IDS is empty — the bot will answer in "
                       "ANY group it is added to.")
    try:
        me = await app.bot.get_me()
        if not me.can_read_all_group_messages:
            logger.warning(
                "Bot privacy mode is ON: trigger-word messages only reach "
                "the bot if it is a group admin or privacy mode is off "
                "(BotFather)."
            )
    except Exception as e:
        logger.warning("getMe check failed: %s", e)

    app.bot_data["health_server"] = start_health_server()


async def post_shutdown(app: Application) -> None:
    stop_health_server(app.bot_data.get("health_server"))
    client = app.bot_data.get("llm")
    if client is not None:
        await client.close()


async def _error_handler(update, context) -> None:
    # Log only — never send a message from the error handler.
    logger.exception("handler error: %s", context.error)


def build_application(settings: Settings) -> Application:
    app = (
        Application.builder()
        .token(settings.telegram_bot_token)
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .build()
    )
    register_handlers(app, settings)
    app.add_error_handler(_error_handler)
    return app
