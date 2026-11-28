"""Telegram handler registration. The old tg/handlers.py (3,771 lines) is
split into: chat.py (routing + LLM conversation), media.py (songs/videos),
voice.py (voice notes)."""
from telegram.ext import CommandHandler, MessageHandler, filters

from bahgat.handlers import chat


def register_handlers(app, settings) -> None:
    app.bot_data["settings"] = settings
    # Command handlers first: a MessageHandler in the same group would
    # otherwise swallow /stats and /about (v1.16 /diag lesson).
    app.add_handler(CommandHandler("about", chat.handle_about))
    app.add_handler(CommandHandler("stats", chat.handle_stats))
    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, chat.handle_message)
    )
