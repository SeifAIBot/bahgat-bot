"""Plugin: YouTube — delegates to tools/youtube.py."""
from tools.youtube import download
async def run(url: str, audio_only: bool = False):
    return download(url, audio_only)
