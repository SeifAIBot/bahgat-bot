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
import hashlib
import json, re, subprocess, os, time, uuid, logging
from pathlib import Path
from urllib.parse import urlparse

from tools import warp as _warp

logger = logging.getLogger(__name__)

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


_BOT_CHECK_MARKERS = (
    "sign in to confirm", "not a bot", "confirm you're not a bot",
    "bot-check", "bot check", "403", "forbidden", "player response",
    "failed to extract",
)


def _is_bot_check_error(detail: str) -> bool:
    """True when a yt-dlp error looks like YouTube refusing the request
    from the server (bot-check). Same markers as tg.handlers'
    _download_error_hint, so the owner hint stays accurate: a bot-check
    failure is reported as 'يوتيوب رافض الطلب من السيرفر', anything
    else gets its own (or no) hint — never a misleading one."""
    s = (detail or "").lower()
    return any(m in s for m in _BOT_CHECK_MARKERS)


def _pick_error_detail(detail: str) -> str:
    """yt-dlp's stderr starts with WARNINGS; the cause is the ERROR line.
    Prefer the last 'ERROR:' / 'yt-dlp: error:' line so the host log
    actually says WHY the download failed (the first 300 chars are
    usually SSL/progress warnings, not the cause)."""
    lines = [ln.strip() for ln in (detail or "").splitlines() if ln.strip()]
    for line in reversed(lines):
        if line.startswith("ERROR:") or line.startswith("yt-dlp: error:"):
            return line[:300]
    return (detail or "")[:300]


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
        raise RuntimeError(f"yt-dlp failed: {_pick_error_detail(detail)}") from e


# v1.1: YouTube's player API is where the bot-check bites (search uses a
# different endpoint and works without it). The Android player client
# bypasses the check without cookies — verified on the training-video
# downloads in this VM (web client + cookies bot-checked every attempt;
# android client downloaded fine). Used by every call that touches the
# player API (resolve + download); search stays as-is, it works.
_YT_PLAYER_CLIENT_ARGS = ["--extractor-args", "youtube:player_client=android"]

# v1.8: the v1.3 chain is live on Cloady but downloads STILL fail there —
# video AND audio both bot-checked live 2026-11-27 (03:57 / 04:01 EET,
# "يوتيوب رافض الطلب من السيرفر") — while the SAME chain works end to
# end in this VM (Marwan Moussa El Kholasa: video OK 10.6s, audio OK
# 18.6s). Root cause is the host, not the code: YouTube bot-checks
# Cloady's datacenter IP; the cookies are valid to Dec 2027 and even
# known-good cookies fail on the web client. Confirmed live 2026-11-27:
# Waad (@D7Bot, added to the test group) downloads the SAME song fine
# from another host (audio 3:19 / 2.3 MB and video, ~1s) — its files
# carry an "@YYYYF" caption and a "بوت تحميل وعد" link, so they may
# come through a backend service/files channel rather than direct
# yt-dlp; that off-Cloady route is a FUTURE option, not this version.
# So the chain is reordered and strengthened instead of debugged:
#   pass 1: plain android FIRST (v1.8 VM probe: android+skip failed
#     twice, plain android succeeded twice — the v1.3 order had the
#     weaker variant first), then android+skip, ios+skip, web+skip.
#   pass 2: the two android variants AGAIN, after a short sleep — the
#     check is intermittent, so a later independent ticket can pass
#     where the first was refused.
#   tv with -f best: the tv client got a player response once where
#     the web client was bot-checked.
#   cookies attempt (web client + --cookies) LAST, only when cookies
#     are configured — unchanged.
# The v1.3 explicit-format attempt (android+skip+fmt18) is dropped:
# its job (naming a format the client actually serves) is covered by
# the tv+best attempt, and the second pass already re-tries android.
# player_skip=configs is a real yt-dlp extractor arg in the installed
# version (used in yt-dlp's own YouTube tests): it skips downloading
# extra client configs, which is one of the requests the bot-check
# bites on. Clients mweb / tv_embedded were checked against the
# installed version's INNERTUBE_CLIENTS: tv and mweb EXIST (mweb
# failed the v1.3 probe with a bot-check, so it is not in the chain);
# tv_embedded does NOT exist (yt-dlp would warn "Skipping unsupported
# client" and silently fall back to defaults — not a real fallback).
# player_client and player_skip are passed as SEPARATE --extractor-args
# flags (yt-dlp merges them; verified live in the VM) so that the argv
# still contains the exact element "youtube:player_client=android"
# that the v1.1 tests assert. Per-attempt timeouts bound the worst
# case: download 180s x 8, resolve 45s x 5. A bot-check failure is fast
# (~5–20s); only a stalled transfer burns the full timeout.
# Attempts are (label, player client, skip_configs, format override).
_YT_NO_COOKIE_ATTEMPTS = (
    ("android", "android", False, None),
    ("android+skip=configs", "android", True, None),
    ("ios+skip=configs", "ios", True, None),
    ("web+skip=configs", "web", True, None),
)
_YT_COOKIES_ATTEMPT = ("web+cookies", "web", True)

# v1.8: sleep between the two download passes so the retries are
# independent tickets, not a burst at the same second. Tests patch this
# to 0 (see test_youtube_fallbacks_v13.py).
_RETRY_PASS_SLEEP_SECONDS = 5


def _js_runtime_args() -> list[str]:
    """--js-runtimes flags for web-client attempts (v1.8). yt-dlp
    enables only deno by default and the Docker image ships node (see
    Dockerfile), so a web attempt must name node explicitly or it runs
    degraded (no JS runtime -> JS challenges unsolved -> bot-check).
    --no-js-runtimes MUST come first: it clears the deno default
    before node is enabled."""
    return ["--no-js-runtimes", "--js-runtimes", "node"]


def _player_client_cli(client: str, skip_configs: bool) -> list[str]:
    """--extractor-args tokens for one attempt: player_client on its
    own flag, player_skip=configs on a second flag when requested."""
    tokens = ["--extractor-args", f"youtube:player_client={client}"]
    if skip_configs:
        tokens += ["--extractor-args", "youtube:player_skip=configs"]
    return tokens


# v1.10 (WARP): the yt-dlp download path — and ONLY it — goes through the
# Cloudflare WARP SOCKS5 proxy when it is up (tools/warp.py). Search
# (search_query) and resolve stay direct: they work from Cloady already,
# and routing them through the tunnel would burn tunnel bandwidth for
# nothing. A download attempt that fails with an error naming the PROXY
# itself (not YouTube) trips a short circuit breaker so the remaining
# attempts in the chain — and the next downloads for a few minutes — go
# direct instead of burning every attempt against a dead tunnel. A
# YouTube bot-check through the proxy does NOT trip it: the chain must
# keep retrying other clients through WARP, that is the whole point.
_PROXY_BREAKER_SECONDS = 300
_PROXY_DOWN_UNTIL = 0.0
_PROXY_ERROR_MARKERS = (
    "proxy", "socks", "connection refused", "errno 111", "errno 61",
    "tunnel connection failed", "unable to connect",
)


def _proxy_args() -> list[str]:
    """--proxy flags for one download attempt: the WARP SOCKS5 URL when
    the proxy is up and the breaker is not tripped, else []. Evaluated
    per attempt, so a breaker tripped mid-chain takes effect on the
    very next attempt. The URL itself is never logged."""
    if time.monotonic() < _PROXY_DOWN_UNTIL:
        return []
    url = _warp.proxy_url()
    if url is None or not _warp.proxy_available():
        return []
    return ["--proxy", url]


def _maybe_trip_proxy_breaker(detail: str) -> None:
    """Trip the breaker when a failed attempt's error names the proxy
    itself. Only called for attempts that actually went through the
    proxy (the caller knows)."""
    global _PROXY_DOWN_UNTIL
    s = (detail or "").lower()
    if any(m in s for m in _PROXY_ERROR_MARKERS):
        _PROXY_DOWN_UNTIL = time.monotonic() + _PROXY_BREAKER_SECONDS
        logger.warning("warp proxy looks dead (%s); downloads go direct for %ss",
                       detail[:120], _PROXY_BREAKER_SECONDS)


def _cookies_args() -> list[str]:
    """--cookies args when the host provides cookies, else [].

    Precedence: YT_COOKIES_FILE (explicit file path) first, then
    YT_COOKIES_CONTENT (raw Netscape cookies.txt content, materialised
    to a 0600 file — see _cookies_content_path()). A set-but-missing
    file, or a set-but-empty content value, logs a warning and proceeds
    without cookies — the bot never crashes over this. The file path
    is never logged, and the cookie CONTENT is never logged anywhere.
    v1.1 fallback ONLY... (see docs/YOUTUBE_COOKIES.md — v1.3: the
    throwaway-account cookies plan is now APPROVED by Seif, but cookies
    are still the LAST resort: download()/resolve_query() only pass
    these args on the final attempt, after the no-cookies chain above
    is exhausted. The cookies MUST come from a THROWAWAY Google/YouTube
    account created for the bot — never from Seif's own account.
    """
    path = (os.environ.get("YT_COOKIES_FILE") or "").strip()
    if path:
        if not os.path.isfile(path):
            logger.warning("YT_COOKIES_FILE is set but the file does not exist; continuing without cookies")
            return []
        return ["--cookies", path]
    content_path = _cookies_content_path()
    if content_path is None:
        return []
    if not os.path.isfile(content_path):
        logger.warning("YT_COOKIES_CONTENT could not be materialised; continuing without cookies")
        return []
    return ["--cookies", content_path]


# Cache for the materialised YT_COOKIES_CONTENT file: only the sha256
# of the content is kept in memory, never the content itself.
_COOKIES_CONTENT_CACHE = {"hash": None, "path": None}
_COOKIES_CONTENT_FILENAME = "youtube_cookies.txt"


def _cookies_content_path() -> str | None:
    """Materialise YT_COOKIES_CONTENT to a file and return its path.

    The file lives under ROOT/data/ (the persistent volume on Cloady,
    /app/data — NOT the repo, and gitignored twice over via `data/` and
    `*cookies*.txt`, so it can never be committed). It is created with
    mode 0600 via os.open (umask can only remove bits from 0600, never
    add them) and written ONCE per distinct content value — repeat calls
    with unchanged content return the cached path without rewriting.
    Empty/whitespace-only content warns and returns None. The content
    is never logged. Returns None on any write failure.
    """
    content = os.environ.get("YT_COOKIES_CONTENT") or ""
    if not content.strip():
        if "YT_COOKIES_CONTENT" in os.environ:
            logger.warning("YT_COOKIES_CONTENT is set but empty; continuing without cookies")
        return None
    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
    cached_path = _COOKIES_CONTENT_CACHE.get("path")
    if _COOKIES_CONTENT_CACHE.get("hash") == digest and cached_path and os.path.isfile(cached_path):
        return cached_path
    path = ROOT / "data" / _COOKIES_CONTENT_FILENAME
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(content if content.endswith("\n") else content + "\n")
        except Exception:
            try:
                os.close(fd)
            except OSError:
                pass
            raise
        os.chmod(path, 0o600)
    except OSError:
        logger.warning("could not write cookies file from YT_COOKIES_CONTENT; continuing without cookies")
        return None
    _COOKIES_CONTENT_CACHE.update({"hash": digest, "path": str(path)})
    return str(path)


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
    # v1.1: ytsearch can return the same video twice — dedupe by video
    # id first. The live فرعون list (18:05 test) also had the SAME song
    # twice under different uploads/titles ("Marwan Moussa - Fr3on
    # (Official Audio)" vs "MARWAN MOUSSA - FR3ON | ...", both 3:47),
    # which video ids cannot catch — so a second pass drops a later
    # entry when its title tokens are a subset of an earlier entry's
    # (or vice versa) AND the durations are equal. The >=3-token floor
    # on the smaller set keeps short titles ("فرعون" alone) from
    # collapsing different songs. First occurrence wins, order kept.
    # (Correction: the brief's "EL 3NWAN twice" was a misread — in the
    # الخلاصه list #3 is النظام (3:40) and #5 is EL 3NWAN (2:58),
    # different songs; the real duplicate was the فرعون pair.)
    seen_ids = set()
    kept = []
    for item in out:
        if item["video_id"] in seen_ids:
            continue
        seen_ids.add(item["video_id"])
        if _is_title_dupe(item, kept):
            continue
        kept.append(item)
    return kept


_MIN_TITLE_TOKENS = 3


def _title_tokens(title: str) -> set[str]:
    """Normalised title tokens for near-dupe detection: lowercased,
    tashkeel/tatweel stripped, alef forms unified, ى→ي, ة→ه, split
    on anything that is not a word character."""
    s = (title or "").lower()
    s = re.sub(r"[\u064b-\u0652\u0640]", "", s)
    s = re.sub(r"[أإآ]", "ا", s).replace("ى", "ي").replace("ة", "ه")
    return {t for t in re.split(r"[^\w]+", s) if t}


def _is_title_dupe(item: dict, kept: list[dict]) -> bool:
    """True when `item` is the same song as an earlier kept entry:
    same duration (both known) and one title's token set is a subset
    of the other's. The token floor keeps a bare one-word title from
    matching a longer title of a different song."""
    tokens = _title_tokens(item.get("title") or "")
    dur = item.get("duration")
    if len(tokens) < _MIN_TITLE_TOKENS or dur is None:
        return False
    for other in kept:
        other_dur = other.get("duration")
        if other_dur is None or other_dur != dur:
            continue
        other_tokens = _title_tokens(other.get("title") or "")
        if len(other_tokens) < _MIN_TITLE_TOKENS:
            continue
        if tokens <= other_tokens or other_tokens <= tokens:
            return True
    return False


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
        base = ["--", target]
    else:
        if "://" in q or q.lower().startswith("http"):
            raise ValueError("only YouTube URLs are allowed; use a search query otherwise")
        base = ["--", f"ytsearch1:{q}"]
    # v1.8: rotate player clients — the bot-check is intermittent, so a
    # failure on one client is retried with the next (plain android
    # first, then android+skip, ios, web — v1.8 VM probe: plain android
    # beat android+skip 2/2). Cookies, if configured, are the last
    # resort only (web client — the Android client takes no cookies, so
    # yt-dlp skips it when cookies are passed).
    attempts = [
        (label, client, skip, False)
        for label, client, skip, _ in _YT_NO_COOKIE_ATTEMPTS
    ]
    cookies = _cookies_args()
    if cookies:
        attempts.append((*_YT_COOKIES_ATTEMPT, True))
    last_detail = ""
    res = None
    for label, client, skip, use_cookies in attempts:
        cmd = ["yt-dlp", "--dump-single-json", "--no-download", "--no-playlist",
               *_player_client_cli(client, skip)]
        if client == "web":
            cmd += _js_runtime_args()
        if use_cookies:
            cmd += cookies
        cmd += base
        try:
            res = _run_yt_dlp(cmd, timeout=45)
            logger.info("youtube resolve succeeded on attempt %s", label)
            break
        except RuntimeError as e:
            last_detail = str(e).removeprefix("yt-dlp failed: ").strip()
            logger.warning("youtube resolve attempt %s failed: %s", label, e)
    if res is None:
        raise RuntimeError(
            f"yt-dlp failed: all {len(attempts)} resolve attempts failed "
            f"(last: {last_detail})")
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
    # v1.1: the Android player client serves NO audio-only format —
    # only the combined format 18 (mp4 640x360, AAC) plus storyboards
    # (verified live: 4 formats, no bestaudio). So the audio selector
    # must fall back to `best` (format 18) and let --extract-audio pull
    # the audio track out of it with ffmpeg; without the /best fallback
    # yt-dlp tries the web client instead and dies on the bot-check.
    # Same for video: a final /best fallback beats a bot-check death.
    fmt = "bestaudio[ext=m4a]/bestaudio/best" if audio_only else "best[height<=480][ext=mp4]/best[height<=480]/best"
    out = str(req_dir / "%(title).50s.%(ext)s")
    # v1.1: --no-thumbnail and --no-subs were REMOVED in newer yt-dlp
    # (requirements.txt pins >=2026.7.4, unbounded above; the Docker
    # image installs the latest). Passing them makes yt-dlp die with
    # "no such option" before ANY network request — that is why BOTH
    # taps failed live while search (no such flags) worked. Neither
    # flag does anything anyway: thumbnails/subs are only written when
    # --write-thumbnail/--write-subs is given.
    # v1.8: the whole download is retried across the client chain —
    # pass 1 (plain android -> android+skip -> ios+skip -> web+skip),
    # then, after a short sleep, pass 2 (the two android variants
    # again), then tv with -f best, and only then — if cookies are
    # configured — once with cookies (web client). No --cookies on the
    # no-cookies attempts: cookies are the last resort. Each attempt is
    # a fresh subprocess; the bot-check is intermittent, so a later
    # attempt can pass where an earlier one was refused. On total
    # failure the raised error names the attempt count and the LAST
    # error's detail, so the owner hint stays accurate: a bot-check
    # last error still maps to "يوتيوب رافض الطلب من السيرفر"
    # (tg/handlers._download_error_hint), a different last error maps
    # to its own hint — the "all attempts failed" prefix itself is the
    # distinct marker for exhaustion in the host log, and it never
    # claims a bot-check it didn't see.
    attempts = [
        (label, client, skip, None, False)
        for label, client, skip, _ in _YT_NO_COOKIE_ATTEMPTS
    ]
    pass2_start = len(attempts)
    attempts += [
        ("android-pass2", "android", False, None, False),
        ("android+skip=configs-pass2", "android", True, None, False),
    ]
    attempts.append(("tv+best", "tv", False, "best", False))
    cookies = _cookies_args()
    if cookies:
        attempts.append((*_YT_COOKIES_ATTEMPT, None, True))
    last_detail = ""
    res = None
    for idx, (label, client, skip, fmt_override, use_cookies) in enumerate(attempts):
        if idx == pass2_start:
            # Short sleep between passes so the retries are independent
            # tickets, not a burst at the same second.
            time.sleep(_RETRY_PASS_SLEEP_SECONDS)
        attempt_fmt = fmt_override or fmt
        # v1.10: --force-ipv4 (research §3g: YouTube scores a whole
        # IPv6 /64 as one unit, so a shared /64 is MORE exposed than a
        # single IPv4; the standard yt-dlp recipe forces IPv4) and the
        # WARP proxy, evaluated fresh per attempt so the circuit
        # breaker can take effect mid-chain.
        proxy_args = _proxy_args()
        cmd = ["yt-dlp", "--no-playlist", "--max-filesize", "50M", "--force-ipv4",
               *_player_client_cli(client, skip)]
        if client == "web":
            cmd += _js_runtime_args()
        if use_cookies:
            cmd += cookies
        cmd += proxy_args
        cmd += ["-f", attempt_fmt, "-o", out, "--print", "after_move:filepath"]
        if audio_only:
            cmd += ["--extract-audio", "--audio-format", "mp3"]
        cmd += ["--", url]
        try:
            res = _run_yt_dlp(cmd, timeout=180)
            logger.info("youtube download succeeded on attempt %s (egress=%s)",
                        label, "warp" if proxy_args else "direct")
            break
        except RuntimeError as e:
            last_detail = str(e).removeprefix("yt-dlp failed: ").strip()
            logger.warning("youtube download attempt %s failed: %s", label, e)
            if proxy_args:
                _maybe_trip_proxy_breaker(last_detail)
    if res is None:
        raise RuntimeError(
            f"yt-dlp failed: all {len(attempts)} download attempts failed "
            f"(last: {last_detail})")
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
