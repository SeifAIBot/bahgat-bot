"""Media — YouTube search/metadata/download + open-source fallbacks.

v2.2 policy (expert review §6):
- YouTube download: ONE plain attempt, audio-only when asked. yt-dlp is
  current, the bgutil PO-token provider is installed (it supplies
  Proof-of-Origin tokens; YT_DLP_POT_PROVIDER_URL points it at a remote
  bgutil server when set), and YTDLP_PROXY_URL routes yt-dlp through an
  egress proxy (e.g. a WARP wireproxy) when set — both are non-fatal
  when unset. No cookies, no retries: on failure the bot says so in
  character, hands over the link, and offers the open-source fallback.
- Open-source fallbacks (Internet Archive / SoundCloud / Audius) are a
  DIFFERENT catalogue — they do not replace YouTube for mainstream
  (Egyptian) songs, and the bot says so instead of presenting them as
  the same song.
- YouTube SEARCH and metadata keep working regardless of download blocks.

Security: only https URLs on the YouTube host allowlist ever reach yt-dlp;
"--" always separates options from the URL; queries go through the
"ytsearch1:" form, never as bare arguments.
"""
import asyncio
import json
import logging
import os
import subprocess
import sys
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from urllib.parse import urlparse

from bahgat.config import data_dir

logger = logging.getLogger(__name__)

MAX_BYTES = 50 * 1024 * 1024  # Telegram bot upload limit
ALLOWED_HOSTS = {"youtube.com", "www.youtube.com", "youtu.be", "music.youtube.com"}
YT_SEARCH_TIMEOUT = 60
YT_DOWNLOAD_TIMEOUT = 300
ARCHIVE_TIMEOUT = 20


class DownloadError(RuntimeError):
    """Any single-attempt download failure, including YouTube bot-checks."""


def validate_youtube_url(url: str) -> str:
    if not isinstance(url, str) or not url.strip():
        raise ValueError("empty URL")
    s = url.strip()
    if s.startswith("-"):
        raise ValueError("URL must not start with '-'")
    parsed = urlparse(s)
    if parsed.scheme != "https":
        raise ValueError(f"only https YouTube URLs are allowed, got {parsed.scheme!r}")
    host = (parsed.hostname or "").lower()
    if host not in ALLOWED_HOSTS:
        raise ValueError(f"host {host!r} is not an allowed YouTube host")
    if parsed.username or parsed.password:
        raise ValueError("URLs with embedded credentials are not allowed")
    return s


def is_youtube_url(value: str) -> bool:
    try:
        validate_youtube_url(value)
        return True
    except ValueError:
        return False


def _proxy_args() -> list:
    """--proxy for yt-dlp when YTDLP_PROXY_URL is set (e.g. a WARP
    wireproxy at socks5://127.0.0.1:1080). Empty = direct. Non-fatal:
    a dead proxy just makes yt-dlp fail into the usual fallback."""
    proxy = os.environ.get("YTDLP_PROXY_URL", "").strip()
    return ["--proxy", proxy] if proxy else []


def _run_yt_dlp(args: list, timeout: int) -> subprocess.CompletedProcess:
    """Run `python -m yt_dlp ...`. Raises DownloadError on any failure.

    The PO-token provider plugin (bgutil-ytdlp-pot-provider, in
    requirements.txt) is picked up by yt-dlp automatically when
    installed; YT_DLP_POT_PROVIDER_URL reaches it through the inherited
    environment, no code needed."""
    cmd = [sys.executable, "-m", "yt_dlp", *_proxy_args(), *args]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError as e:
        raise DownloadError("yt-dlp is not installed") from e
    except subprocess.TimeoutExpired as e:
        raise DownloadError(f"yt-dlp timed out after {timeout}s") from e
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip().splitlines()
        raise DownloadError(detail[-1][:300] if detail else "yt-dlp failed")
    return proc


def search_youtube(query: str, limit: int = 5) -> list:
    """Metadata-only YouTube search. Returns [{id,title,url,duration}] —
    never raises; an empty list means search failed or found nothing."""
    query = (query or "").strip()
    if not query:
        return []
    try:
        proc = _run_yt_dlp(
            ["--flat-playlist", "--dump-single-json", "--no-warnings",
             f"ytsearch{limit}:{query}"],
            timeout=YT_SEARCH_TIMEOUT,
        )
    except DownloadError as e:
        logger.warning("youtube search failed: %s", e)
        return []
    try:
        data = json.loads(proc.stdout)
    except (json.JSONDecodeError, ValueError):
        return []
    out = []
    for entry in data.get("entries") or []:
        vid = entry.get("id")
        if not vid:
            continue
        out.append({
            "id": vid,
            "title": entry.get("title") or "",
            "url": f"https://www.youtube.com/watch?v={vid}",
            "duration": entry.get("duration"),
        })
    return out[:limit]


def download_once(url: str, audio_only: bool = False, out_dir=None) -> Path:
    """ONE plain download attempt. No proxy, no cookies, no retries.

    Returns the downloaded file path (caller deletes it after sending).
    Raises DownloadError on any failure — the caller replies in character
    with the link and moves to the open-source fallback.
    """
    url = validate_youtube_url(url)
    d = Path(out_dir) if out_dir else (data_dir() / "downloads" / uuid.uuid4().hex)
    d.mkdir(parents=True, exist_ok=True)
    out_tmpl = str(d / "%(id)s.%(ext)s")
    args = ["--no-playlist", "--no-warnings", "--max-filesize", str(MAX_BYTES)]
    if audio_only:
        args += ["-x", "--audio-format", "mp3"]
    else:
        args += ["-f", "bv*[height<=480]+ba/b[height<=480]/b",
                 "--merge-output-format", "mp4"]
    args += ["-o", out_tmpl, "--", url]
    _run_yt_dlp(args, timeout=YT_DOWNLOAD_TIMEOUT)
    files = [p for p in d.iterdir() if p.is_file() and not p.name.endswith(".part")]
    if not files:
        raise DownloadError("yt-dlp produced no file")
    f = files[0]
    if f.stat().st_size > MAX_BYTES:
        f.unlink(missing_ok=True)
        raise DownloadError("file exceeds the 50 MB Telegram limit")
    return f


# ---------------------------------------------------------------------------
# Permitted fallback sources
# ---------------------------------------------------------------------------

def search_internet_archive(query: str, limit: int = 3) -> list:
    """Internet Archive advanced search, audio only. Never raises."""
    query = (query or "").strip()
    if not query:
        return []
    params = {
        "q": f"{query} AND mediatype:audio",
        "fl[]": ["identifier", "title"],
        "rows": str(limit),
        "output": "json",
    }
    url = "https://archive.org/advancedsearch.php?" + urllib.parse.urlencode(params)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "bahgat-bot/2.0"})
        with urllib.request.urlopen(req, timeout=ARCHIVE_TIMEOUT) as r:
            data = json.loads(r.read().decode("utf-8", errors="replace"))
    except Exception as e:
        logger.warning("archive.org search failed: %s", e)
        return []
    out = []
    for doc in (data.get("response") or {}).get("docs") or []:
        ident = doc.get("identifier")
        if not ident:
            continue
        out.append({
            "title": doc.get("title") or ident,
            "url": f"https://archive.org/details/{ident}",
            "source": "Internet Archive",
        })
    return out[:limit]


def _search_extractor(prefix: str, query: str, source: str, limit: int) -> list:
    try:
        proc = _run_yt_dlp(
            ["--flat-playlist", "--dump-single-json", "--no-warnings",
             f"{prefix}{limit}:{query}"],
            timeout=YT_SEARCH_TIMEOUT,
        )
        data = json.loads(proc.stdout)
    except (DownloadError, json.JSONDecodeError, ValueError) as e:
        logger.warning("%s search failed: %s", source, e)
        return []
    out = []
    for entry in data.get("entries") or []:
        url = entry.get("url") or entry.get("webpage_url") or ""
        if not url or not url.startswith("http"):
            continue
        out.append({"title": entry.get("title") or "",
                    "url": url, "source": source})
    return out[:limit]


def search_open_sources(query: str, limit_per_source: int = 2) -> list:
    """Search the permitted fallback sources. Returns up to
    3 * limit_per_source results: Internet Archive, SoundCloud, Audius —
    openly licensed / Creative Commons content only. Never raises."""
    results = []
    results += search_internet_archive(query, limit_per_source)
    results += _search_extractor("scsearch", query, "SoundCloud", limit_per_source)
    results += _search_extractor("audiussearch", query, "Audius", limit_per_source)
    return results


async def asearch_open_sources(query: str, limit_per_source: int = 2) -> list:
    return await asyncio.to_thread(search_open_sources, query, limit_per_source)


async def asearch_youtube(query: str, limit: int = 5) -> list:
    return await asyncio.to_thread(search_youtube, query, limit)


async def adownload_once(url: str, audio_only: bool = False, out_dir=None) -> Path:
    return await asyncio.to_thread(download_once, url, audio_only, out_dir)
