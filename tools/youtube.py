"""YouTube — yt-dlp. 480p default, 50 MB Telegram bot limit.
Fixes: --no-playlist, --max-filesize 50M (checked before download completes),
per-request UUID subfolder, capture the real output path from yt-dlp,
resolve paths against project root, delete after sending (caller responsibility).

Security (v0.5, Workstream A):
- validate_youtube_url(): https only, host in ALLOWED_HOSTS, reject any
  input starting with "-". Any other host / scheme / option-like input
  raises ValueError and is never passed to yt-dlp.
- "--" is inserted immediately before the URL argument in every yt-dlp
  command, so a URL can never be parsed as an option.
- Raw user text is never a bare yt-dlp argument: plain-text queries go
  through resolve_query(), which builds a single "ytsearch1:<query>"
  argument (after "--").
- If yt-dlp is not installed, resolve_query/download fail cleanly with
  RuntimeError (callers show an in-character failure) — never fake results.
"""
import json, subprocess, os, uuid
from pathlib import Path
from urllib.parse import urlparse

MAX_BYTES = 50 * 1024 * 1024
ROOT = Path(__file__).resolve().parents[1]
ALLOWED_HOSTS = {"youtube.com", "www.youtube.com", "youtu.be", "music.youtube.com"}


def validate_youtube_url(url: str) -> str:
    """Validate a YouTube URL. Returns the stripped URL.

    Raises ValueError unless: https scheme, host in ALLOWED_HOSTS,
    no leading '-', no embedded credentials.
    """
    if not isinstance(url, str) or not url.strip():
        raise ValueError("empty URL")
    s = url.strip()
    if s.startswith("-"):
        raise ValueError("URL must not start with '-'")
    parsed = urlparse(s)
    if parsed.scheme != "https":
        raise ValueError(f"only https YouTube URLs are allowed, got scheme {parsed.scheme!r}")
    host = (parsed.hostname or "").lower()
    if host not in ALLOWED_HOSTS:
        raise ValueError(f"host {host!r} is not an allowed YouTube host")
    if parsed.username or parsed.password:
        raise ValueError("URLs with embedded credentials are not allowed")
    return s


def _is_youtube_url(value: str) -> bool:
    try:
        validate_youtube_url(value)
        return True
    except ValueError:
        return False


def _run_yt_dlp(args: list[str], timeout: int) -> subprocess.CompletedProcess:
    """Run yt-dlp. FileNotFoundError (not installed) and non-zero exits
    both become RuntimeError with a caller-safe message."""
    try:
        return subprocess.run(args, check=True, timeout=timeout,
                              capture_output=True, text=True)
    except FileNotFoundError as e:
        raise RuntimeError("yt-dlp is not installed on this host") from e
    except subprocess.CalledProcessError as e:
        detail = (e.stderr or e.stdout or "").strip()
        raise RuntimeError(f"yt-dlp failed: {detail[:300]}") from e


def search_query(query: str, limit: int = 5) -> list[dict]:
    """Search YouTube for up to `limit` results (v0.8 pick-list).

    Returns [{video_id, url, title, duration, thumbnail}] where duration
    is seconds (or None) and thumbnail is a public i.ytimg.com URL.
    Uses a single "ytsearchN:<query>" argument (after "--") with
    --flat-playlist (metadata-only, fast) — raw user text is never a bare
    yt-dlp argument, and URLs / option-like input are rejected exactly
    like in resolve_query(). Raises ValueError / RuntimeError the same
    way; returns [] only when the search legitimately finds nothing.
    """
    if not isinstance(query, str) or not query.strip():
        raise ValueError("empty query")
    q = query.strip()
    if q.startswith("-"):
        raise ValueError("query must not start with '-'")
    if _is_youtube_url(q) or "://" in q or q.lower().startswith("http"):
        raise ValueError("search_query takes a plain-text query, not a URL")
    n = max(1, min(int(limit), 10))
    cmd = ["yt-dlp", "--dump-single-json", "--no-download", "--no-playlist",
           "--flat-playlist", "--", f"ytsearch{n}:{q}"]
    res = _run_yt_dlp(cmd, timeout=60)
    try:
        data = json.loads(res.stdout)
    except (json.JSONDecodeError, ValueError) as e:
        raise RuntimeError("yt-dlp returned unparsable metadata") from e
    entries = []
    if isinstance(data, dict):
        entries = data.get("entries") or []
    out = []
    for entry in entries[:n]:
        if not isinstance(entry, dict) or not entry.get("id"):
            continue
        video_id = str(entry["id"])
        url = f"https://www.youtube.com/watch?v={video_id}"
        duration = entry.get("duration")
        try:
            duration = int(duration) if duration is not None else None
        except (TypeError, ValueError):
            duration = None
        thumb = entry.get("thumbnail")
        if not thumb:
            thumbs = entry.get("thumbnails") or []
            if isinstance(thumbs, list) and thumbs:
                last = thumbs[-1] if isinstance(thumbs[-1], dict) else {}
                thumb = last.get("url")
        if not thumb:
            thumb = f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg"
        out.append({
            "video_id": video_id,
            "url": url,
            "title": (entry.get("title") or "").strip() or video_id,
            "duration": duration,
            "thumbnail": thumb,
        })
    return out


def resolve_query(query: str, audio_only: bool = False) -> dict:
    """Resolve a YouTube URL or a plain-text search query to video metadata.

    Returns {"video_id", "url", "title", "duration", "approx_size"} where
    duration is seconds (or None) and approx_size is bytes (or None).
    A valid YouTube URL is used directly (metadata still fetched via
    --dump-single-json); anything else is searched as a single
    "ytsearch1:<query>" argument built by this code — raw user text is
    never passed as a bare yt-dlp argument. Raises ValueError for
    option-like input or non-YouTube URLs, RuntimeError if yt-dlp is
    missing or fails.
    """
    if not isinstance(query, str) or not query.strip():
        raise ValueError("empty query")
    q = query.strip()
    if q.startswith("-"):
        raise ValueError("query must not start with '-'")
    if _is_youtube_url(q):
        target = validate_youtube_url(q)
        cmd = ["yt-dlp", "--dump-single-json", "--no-download", "--no-playlist",
               "--", target]
    else:
        if "://" in q or q.lower().startswith("http"):
            raise ValueError("only YouTube URLs are allowed; use a search query otherwise")
        cmd = ["yt-dlp", "--dump-single-json", "--no-download", "--no-playlist",
               "--", f"ytsearch1:{q}"]
    res = _run_yt_dlp(cmd, timeout=60)
    try:
        data = json.loads(res.stdout)
    except (json.JSONDecodeError, ValueError) as e:
        raise RuntimeError("yt-dlp returned unparsable metadata") from e
    if isinstance(data, dict) and isinstance(data.get("entries"), list) and data["entries"]:
        data = data["entries"][0]
    if not isinstance(data, dict) or not data.get("id"):
        raise RuntimeError("yt-dlp returned no video")
    video_id = str(data["id"])
    webpage_url = data.get("webpage_url") or ""
    if webpage_url and _is_youtube_url(webpage_url):
        url = validate_youtube_url(webpage_url)
    elif _is_youtube_url(q):
        url = validate_youtube_url(q)
    else:
        url = f"https://www.youtube.com/watch?v={video_id}"
    duration = data.get("duration")
    try:
        duration = int(duration) if duration is not None else None
    except (TypeError, ValueError):
        duration = None
    approx_size = data.get("filesize_approx")
    if approx_size is None:
        approx_size = data.get("filesize")
    try:
        approx_size = int(approx_size) if approx_size is not None else None
    except (TypeError, ValueError):
        approx_size = None
    return {
        "video_id": video_id,
        "url": url,
        "title": data.get("title") or "",
        "duration": duration,
        "approx_size": approx_size,
    }


def download(url_or_query: str, audio_only: bool, out_dir: str | None = None) -> str:
    """Download a YouTube video (or audio) and return the local file path.

    Accepts a validated YouTube URL OR a plain search query — a query is
    resolved via resolve_query() first, then the resolved URL is
    downloaded. Non-YouTube URLs and option-like input raise ValueError.
    out_dir, when given, is used as the request folder; otherwise a
    per-request UUID subfolder under data/downloads/ is created.
    Keeps --no-playlist --max-filesize 50M, captures the real filepath,
    and enforces the 50 MB post-download check.
    """
    if not isinstance(url_or_query, str) or not url_or_query.strip():
        raise ValueError("empty URL or query")
    s = url_or_query.strip()
    if s.startswith("-"):
        raise ValueError("URL/query must not start with '-'")
    if _is_youtube_url(s):
        url = validate_youtube_url(s)
    elif "://" in s or s.lower().startswith("http"):
        raise ValueError("only YouTube URLs are allowed")
    else:
        url = resolve_query(s, audio_only=audio_only)["url"]
    req_dir = Path(out_dir) if out_dir else (ROOT / "data" / "downloads" / uuid.uuid4().hex)
    req_dir.mkdir(parents=True, exist_ok=True)
    fmt = "bestaudio[ext=m4a]/bestaudio" if audio_only else "best[height<=480][ext=mp4]/best[height<=480]"
    out = str(req_dir / "%(title).50s.%(ext)s")
    cmd = ["yt-dlp", "--no-playlist", "--max-filesize", "50M", "--no-thumbnail", "--no-subs",
           "-f", fmt, "-o", out, "--print", "after_move:filepath"]
    if audio_only:
        cmd += ["--extract-audio", "--audio-format", "mp3"]
    cmd += ["--", url]
    res = _run_yt_dlp(cmd, timeout=300)
    # Last non-empty line is the filepath printed by --print after_move:filepath
    lines = [l.strip() for l in res.stdout.splitlines() if l.strip()]
    if not lines:
        raise RuntimeError("yt-dlp did not return a file path")
    path = lines[-1]
    if not os.path.exists(path):
        raise RuntimeError(f"downloaded file not found: {path}")
    if os.path.getsize(path) > MAX_BYTES:
        os.unlink(path)
        raise RuntimeError("الفيديو أكبر من 50 ميجا، جرب صوت بس أو فيديو أقصر")
    return path
