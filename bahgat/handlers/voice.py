"""Voice-note replies — speak a reply with the generic TTS voice. On any
synthesis failure the text is sent instead."""
import logging

from telegram import Update

from bahgat import voice

logger = logging.getLogger(__name__)


async def send_voice_reply(update: Update, reply_text: str,
                           rvc_url: str = "") -> None:
    """Speak a reply. rvc_url is the separate RVC worker's base URL
    (empty = Edge TTS only); voice.send_voice falls back to Edge TTS
    on any worker failure."""
    msg = update.effective_message
    try:
        ogg = await voice.send_voice(reply_text, rvc_url=rvc_url)
    except Exception as e:
        logger.warning("voice synthesis failed, falling back to text: %s", e)
        await msg.reply_text(reply_text)
        return
    try:
        with open(ogg, "rb") as fh:
            await msg.reply_voice(fh)
    finally:
        ogg.unlink(missing_ok=True)
