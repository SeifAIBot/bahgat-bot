"""Plugin: voice — delegates to tools/voice.py (Edge TTS v1)."""
from tools.voice import synthesize
async def run(text: str):
    return await synthesize(text)
