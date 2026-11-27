"""Voice — Edge TTS v1, ar-EG male (Shakir). Returns ogg for Telegram voice notes.
Caller must delete the returned file after sending (and the intermediate mp3).

v0.5 (Workstream A): ffmpeg runs via asyncio.to_thread (never a blocking
subprocess.run inside async code); Edge TTS is wrapped in
asyncio.wait_for(..., timeout=15) and on any failure the exception is
raised (caller falls back to text) and partial .mp3/.ogg files are
deleted. On success only the .mp3 is deleted and the .ogg is returned.

v1.9: synthesis is retried ONCE inside this module (2 attempts total) and
each failure is LOGGED here — before v1.9 a dead voice path failed
silently at this layer (the caller retried + logged, but the module
itself swallowed the cause). The retry matters because Microsoft
changed the token check in October 2026 (Sec-MS-GEC v2): every
edge-tts below 7.3.0 is rejected at the WebSocket handshake with 403,
so the pin is edge-tts==7.3.1 in requirements.txt.
"""
import asyncio, edge_tts, logging, subprocess, os, uuid
from pathlib import Path

logger = logging.getLogger(__name__)

VOICE = "ar-EG-ShakirNeural"
ROOT = Path(__file__).resolve().parents[1]

async def synthesize(text: str, out_dir: str | None = None) -> str:
    d = Path(out_dir) if out_dir else (ROOT / "data" / "voice")
    d.mkdir(parents=True, exist_ok=True)
    base = d / uuid.uuid4().hex
    mp3 = str(base) + ".mp3"
    ogg = str(base) + ".ogg"
    try:
        # One retry on the TTS save itself: a single handshake/network
        # flake must not kill the voice note. Each failure is logged
        # with attempt number + exception so a dead voice path is
        # visible in the host logs (data/bot.log) instead of silent.
        last_exc: Exception | None = None
        for attempt in (1, 2):
            try:
                comm = edge_tts.Communicate(text, VOICE, rate="+5%", pitch="+0Hz")
                await asyncio.wait_for(comm.save(mp3), timeout=15)
                break
            except Exception as e:
                last_exc = e
                logger.warning(
                    "edge-tts synthesize failed (attempt %s/2): %s: %s",
                    attempt, type(e).__name__, e,
                )
                try:
                    if os.path.exists(mp3):
                        os.unlink(mp3)
                except Exception:
                    pass
                if attempt == 1:
                    await asyncio.sleep(1)
        else:
            # Both attempts failed without a break — surface the last one.
            raise last_exc  # type: ignore[misc]
        await asyncio.to_thread(
            subprocess.run,
            ["ffmpeg", "-y", "-i", mp3, "-c:a", "libopus", ogg],
            check=True, capture_output=True, timeout=60,
        )
    except Exception:
        # Failure: delete BOTH partial files, then raise so the caller
        # can fall back to text.
        for p in (mp3, ogg):
            try:
                if os.path.exists(p):
                    os.unlink(p)
            except Exception:
                pass
        raise
    # Success: only the intermediate mp3 is deleted; the ogg is returned.
    try:
        if os.path.exists(mp3):
            os.unlink(mp3)
    except Exception:
        pass
    return ogg
