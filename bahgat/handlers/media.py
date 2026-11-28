"""Media requests — songs and videos.

Flow (v2.0 policy):
1. YouTube URL in the message, or a query resolved through YouTube search.
2. ONE plain download attempt (no WARP, no cookies, no retries).
3. On failure: reply in character with the link + a short note, and look
   for the track on permitted sources (Internet Archive / SoundCloud /
   Audius — openly licensed) and offer those links.
"""
import logging
import re
import shutil

from telegram import Update
from telegram.ext import ContextTypes

from bahgat import db, media

logger = logging.getLogger(__name__)

_URL_RE = re.compile(r"https?://\S+")

# Words stripped to turn "بهجت شغل اغنية ويجز الجديدة" into the query
# "ويجز الجديدة".
_QUERY_NOISE = ("بهجوتي", "بهجت", "يا", "شغل", "شغّل", "هات", "هاتلي",
                "جيب", "جيبلي", "نزل", "نزلي", "عايز", "عاوز", "اغنية",
                "أغنية", "اغنيه", "أغنيه", "سونج", "تراك", "كليب", "فيديو",
                "من", "يوتيوب", "بتاع", "بتاعة", "لو", "سمحت", "بصوت", "صوت")

MEDIA_FAIL_LINES = [
    "يوتيوب قافل في وشي النهارده، مش راضي يديني الملف — خد اللينك واسمعه بنفسك:",
    "حاولت أجيبهالك ويوتيوب رفض يديني حاجة، قصادك لينكين: الأصل، وبديل مفتوح.",
    "التحميل من يوتيوب واقف معايا دلوقتي. اللينك تحت، ولو لقيت بديل مفتوح حطيته جنبه.",
]

_VIDEO_WORDS = ("فيديو", "كليب", "video")


def extract_youtube_url(text: str) -> str | None:
    for m in _URL_RE.finditer(text or ""):
        candidate = m.group(0).rstrip(".,!؟?)")
        if media.is_youtube_url(candidate):
            return candidate
    return None


def wants_video(text: str) -> bool:
    t = text or ""
    return any(w in t for w in _VIDEO_WORDS)


def query_from_text(text: str) -> str:
    words = (text or "").split()
    kept = [w for w in words if w not in _QUERY_NOISE]
    return " ".join(kept).strip()


def format_fallback_message(link: str, alternatives: list) -> str:
    import random
    parts = [random.choice(MEDIA_FAIL_LINES), link]
    if alternatives:
        # Honest label (expert review §6): these are DIFFERENT catalogues,
        # not the same song from another tap.
        parts.append("ودي بدائل من مصادر تانية، مش نفس الأغنية بالضرورة:")
        for alt in alternatives[:3]:
            parts.append(f"- {alt['title']} ({alt['source']}): {alt['url']}")
    return "\n".join(parts)


async def handle(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str) -> None:
    msg = update.effective_message
    chat_id = msg.chat_id
    audio_only = not wants_video(text)

    url = extract_youtube_url(text)
    title = ""
    if not url:
        query = query_from_text(text)
        if not query:
            await msg.reply_text("قولي اسم الأغنية أو الفيديو الأول يا عم.")
            return
        results = await media.asearch_youtube(query, limit=3)
        if results:
            url = results[0]["url"]
            title = results[0]["title"]
        else:
            # YouTube search itself found nothing / is blocked: go straight
            # to the permitted sources (labelled as a different catalogue).
            alts = await media.asearch_open_sources(query)
            if alts:
                lines = ["يوتيوب ملقتش فيه حاجة، بس لقيت لك ده من مصادر "
                         "تانية (مش يوتيوب، فممكن متكونش نفس الأغنية):"]
                for alt in alts[:3]:
                    lines.append(f"- {alt['title']} ({alt['source']}): {alt['url']}")
                reply = "\n".join(lines)
            else:
                reply = "دورت في كل حتة ومفيش حاجة طلعت — متأكد من الاسم؟"
            await msg.reply_text(reply, disable_web_page_preview=True)
            db.add_message(chat_id, "bot", reply)
            return

    # ONE plain download attempt.
    try:
        path = await media.adownload_once(url, audio_only=audio_only)
    except media.DownloadError as e:
        logger.warning("download failed for %s: %s", url, e)
        alts = await media.asearch_open_sources(title or query_from_text(text))
        reply = format_fallback_message(url, alts)
        await msg.reply_text(reply, disable_web_page_preview=True)
        db.add_message(chat_id, "bot", reply)
        return

    try:
        with open(path, "rb") as fh:
            if audio_only:
                await msg.reply_audio(fh, title=title or None)
            else:
                await msg.reply_video(fh, caption=title or None)
        db.add_message(chat_id, "bot", f"[بعت الملف: {title or url}]")
    finally:
        shutil.rmtree(path.parent, ignore_errors=True)
