"""Voice notes — Edge TTS voice (ar-EG male), returned as ogg/opus
for Telegram.

v2.2: the RVC voice-cloning track is KEPT, not dropped — but RVC never
runs inside this 1 GB container (it needs ~6 GB RAM). `send_voice()`
tries a separate RVC worker first when RVC_URL is set, and falls back
to the generic Edge TTS voice on any failure. With RVC_URL unset the
bot is Edge TTS only. On any failure the exception is raised and the
caller falls back to plain text.
"""
import asyncio
import logging
import re
import subprocess
import uuid
from pathlib import Path

from bahgat.config import data_dir

logger = logging.getLogger(__name__)

VOICE = "ar-EG-ShakirNeural"  # generic Microsoft TTS voice — not a clone
_TIMEOUT = 15

_URL_RE = re.compile(r"https?://\S+")
_MD_RE = re.compile(r"[*_`#>\[\]()]")


def clean_for_tts(text: str, max_chars: int = 600) -> str:
    """Strip links, markdown and citation markers so the voice note sounds
    like speech, not a page being read out."""
    t = _URL_RE.sub("اللينك", text or "")
    t = re.sub(r"\[\d+\]", "", t)
    t = _MD_RE.sub("", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t[:max_chars]


async def _edge_mp3(text: str, out_dir=None) -> Path:
    """Text -> Edge TTS mp3. Caller deletes the mp3 afterwards."""
    import edge_tts  # lazy: only needed when a voice note is requested

    d = Path(out_dir) if out_dir else (data_dir() / "voice")
    d.mkdir(parents=True, exist_ok=True)
    mp3 = d / (uuid.uuid4().hex + ".mp3")
    comm = edge_tts.Communicate(clean_for_tts(text), VOICE, rate="+5%")
    await asyncio.wait_for(comm.save(str(mp3)), timeout=_TIMEOUT)
    return mp3


async def _convert_via_rvc(mp3: Path, rvc_url: str, timeout: int = 90) -> Path:
    """POST the Edge TTS mp3 to the RVC worker; expect ogg/opus back.

    Worker protocol (the seam for the future worker, documented in the
    README): POST {rvc_url}/convert, multipart field "audio" (the mp3),
    form field index_rate=0.75; the worker returns audio/ogg. Raises on
    any HTTP or transport failure — the caller falls back to Edge TTS."""
    import httpx

    ogg = mp3.with_suffix(".rvc.ogg")
    async with httpx.AsyncClient(timeout=timeout) as client:
        with open(mp3, "rb") as fh:
            resp = await client.post(
                rvc_url.rstrip("/") + "/convert",
                files={"audio": ("input.mp3", fh.read(), "audio/mpeg")},
                data={"index_rate": "0.75"},
            )
        resp.raise_for_status()
    ogg.write_bytes(resp.content)
    return ogg


async def send_voice(text: str, out_dir=None, rvc_url: str = "") -> Path:
    """Text -> ogg/opus voice note, RVC first when configured.

    rvc_url: base URL of the separate RVC worker. Empty = Edge TTS only.
    The worker converts the Edge TTS mp3 into the character's voice; on
    ANY failure the generic Edge voice is sent instead — the turn never
    fails for voice.
    """
    if (rvc_url or "").strip():
        try:
            mp3 = await _edge_mp3(text, out_dir)
            try:
                return await _convert_via_rvc(mp3, rvc_url.strip())
            finally:
                mp3.unlink(missing_ok=True)
        except Exception as e:
            logger.warning("RVC worker failed (%s) — Edge TTS fallback", e)
    return await synthesize(text, out_dir=out_dir)


async def synthesize(text: str, out_dir=None) -> Path:
    """Text -> ogg/opus voice note via Edge TTS. Raises on failure
    (caller sends text)."""
    d = Path(out_dir) if out_dir else (data_dir() / "voice")
    d.mkdir(parents=True, exist_ok=True)
    ogg = d / (uuid.uuid4().hex + ".ogg")
    mp3: Path | None = None
    try:
        mp3 = await _edge_mp3(text, out_dir)
        await asyncio.to_thread(
            subprocess.run,
            ["ffmpeg", "-y", "-i", str(mp3), "-c:a", "libopus", str(ogg)],
            check=True, capture_output=True, timeout=60,
        )
    except Exception:
        if mp3 is not None:
            mp3.unlink(missing_ok=True)
        ogg.unlink(missing_ok=True)
        raise
    mp3.unlink(missing_ok=True)
    return ogg
