"""YouTube no-cookies fallback chain + cookies-content env var (v1.3).

Live evidence: v1.1's Android client is live on Cloady but downloads
STILL fail there (2026-11-26 19:56 EET, "يوتيوب رافض الطلب من السيرفر").
VM probe (yt-dlp 2026.11.23) showed the bot-check is INTERMITTENT and
client-dependent: plain android metadata 0/4, android+player_skip=configs
2/4 and the only variant that produced a real download (Rick Astley
dQw4w9WgXcQ: video 11,829,048 bytes mp4, audio 3,708,429 bytes mp3).

These tests mock _run_yt_dlp (no network). Live VM downloads are the
manual verification — see the v1.3 report, not this file.

v1.8 reorder (2026-11-27): plain android FIRST (VM probe: android+skip
failed twice, plain android succeeded twice — video OK 10.6s, audio OK
18.6s on El Kholasa), then android+skip, ios+skip, web+skip, then a
second pass over the two android variants after a short sleep, then
tv with -f best, cookies LAST. The v1.3 explicit-format attempt
(android+skip+fmt18) is dropped — tv+best covers its job.

Cookie fixtures here are OBVIOUSLY FAKE values. No real cookie value
appears anywhere in this file.
"""
import json
import logging
import os
import stat
from types import SimpleNamespace

import pytest

import tools.youtube as yt
from tg.handlers import _download_error_hint

BOT_CHECK = "ERROR: [youtube] x: Sign in to confirm you're not a bot."
FORMAT_ERR = "ERROR: [youtube] x: Requested format is not available"

FAKE_COOKIES = (
    "# Netscape HTTP Cookie File\n"
    ".youtube.com\tTRUE\t/\tTRUE\t1893456000\tFAKE_COOKIE_SECRET_xyz\tfake-value-123\n"
)


@pytest.fixture(autouse=True)
def _clean_cookies_env(monkeypatch):
    monkeypatch.delenv("YT_COOKIES_FILE", raising=False)
    monkeypatch.delenv("YT_COOKIES_CONTENT", raising=False)
    monkeypatch.setattr(yt, "_COOKIES_CONTENT_CACHE",
                        {"hash": None, "path": None})
    # The v1.8 inter-pass sleep is real time — tests patch it to 0
    # except the one test that asserts it happens.
    monkeypatch.setattr(yt, "_RETRY_PASS_SLEEP_SECONDS", 0)
    yield
    monkeypatch.delenv("YT_COOKIES_FILE", raising=False)
    monkeypatch.delenv("YT_COOKIES_CONTENT", raising=False)


def _bot_check_failure(argv, **kwargs):
    raise RuntimeError(f"yt-dlp failed: {BOT_CHECK}")


def _extractor_values(argv):
    """All values passed to --extractor-args flags, in order."""
    return [argv[i + 1] for i, a in enumerate(argv) if a == "--extractor-args"]


# --- fallback chain: download ---------------------------------------------

def test_download_retries_next_client_on_failure(monkeypatch, tmp_path):
    """Failure on client N retries with client N+1, in chain order."""
    target = tmp_path / "video.mp4"
    target.write_bytes(b"x" * 10)
    calls = []
    outcomes = [RuntimeError(f"yt-dlp failed: {BOT_CHECK}"),
                RuntimeError(f"yt-dlp failed: {BOT_CHECK}"),
                SimpleNamespace(stdout=str(target) + "\n",
                                stderr="", returncode=0)]

    def fake_run(argv, **kwargs):
        calls.append(argv)
        outcome = outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    monkeypatch.setattr(yt, "_run_yt_dlp", fake_run)
    assert yt.download(
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ", False,
        out_dir=str(tmp_path / "req")) == str(target)
    assert len(calls) == 3
    extractors = [_extractor_values(c) for c in calls]
    # Plain android first (v1.8 order), then android+skip, then ios.
    assert extractors[0] == ["youtube:player_client=android"]
    assert extractors[1] == ["youtube:player_client=android",
                             "youtube:player_skip=configs"]
    assert extractors[2] == ["youtube:player_client=ios",
                             "youtube:player_skip=configs"]
    # No --cookies anywhere: nothing configured.
    assert all("--cookies" not in c for c in calls)


def test_download_chain_order_v18(monkeypatch, tmp_path):
    """All no-cookies attempts run in v1.8 order: pass 1 (android,
    android+skip, ios+skip, web+skip), pass 2 (android, android+skip),
    tv with -f best. Exhaustion names the count and the last error —
    not a bot-check it didn't see."""
    calls = []

    def fake_run(argv, **kwargs):
        calls.append(argv)
        raise RuntimeError(f"yt-dlp failed: {FORMAT_ERR}")

    monkeypatch.setattr(yt, "_run_yt_dlp", fake_run)
    with pytest.raises(RuntimeError) as excinfo:
        yt.download("https://www.youtube.com/watch?v=dQw4w9WgXcQ", False,
                    out_dir=str(tmp_path / "req"))
    assert len(calls) == 7  # pass 1 (4) + pass 2 (2) + tv (1)
    extractors = [_extractor_values(c) for c in calls]
    assert extractors == [
        ["youtube:player_client=android"],
        ["youtube:player_client=android", "youtube:player_skip=configs"],
        ["youtube:player_client=ios", "youtube:player_skip=configs"],
        ["youtube:player_client=web", "youtube:player_skip=configs"],
        ["youtube:player_client=android"],
        ["youtube:player_client=android", "youtube:player_skip=configs"],
        ["youtube:player_client=tv"],
    ]
    fmts = [c[c.index("-f") + 1] for c in calls]
    assert fmts[:6] == ["best[height<=480][ext=mp4]/best[height<=480]/best"] * 6
    assert fmts[6] == "best"
    assert "all 7 download attempts failed" in str(excinfo.value)
    assert "Requested format is not available" in str(excinfo.value)
    # The last error was a format error, NOT a bot-check: the owner
    # hint must say so, not "YouTube refused the request".
    assert _download_error_hint(excinfo.value) == "مفيش صيغة مناسبة للفيديو ده"


def test_download_audio_chain_v18(monkeypatch, tmp_path):
    """Audio chain: same 7 attempts; the tv attempt uses -f best and
    still extracts mp3 from it."""
    calls = []

    def fake_run(argv, **kwargs):
        calls.append(argv)
        raise RuntimeError(f"yt-dlp failed: {BOT_CHECK}")

    monkeypatch.setattr(yt, "_run_yt_dlp", fake_run)
    with pytest.raises(RuntimeError) as excinfo:
        yt.download("https://www.youtube.com/watch?v=dQw4w9WgXcQ", True,
                    out_dir=str(tmp_path / "req"))
    assert len(calls) == 7
    fmts = [c[c.index("-f") + 1] for c in calls]
    assert fmts[:6] == ["bestaudio[ext=m4a]/bestaudio/best"] * 6
    assert fmts[6] == "best"
    assert all("--extract-audio" in c for c in calls)
    assert "all 7 download attempts failed" in str(excinfo.value)
    # Exhaustion after bot-checks: the hint still says YouTube refused
    # the request — that IS what the last error was.
    assert _download_error_hint(excinfo.value) == "يوتيوب رافض الطلب من السيرفر"


def test_download_second_pass_sleeps_once(monkeypatch, tmp_path):
    """The short sleep fires exactly once, between pass 1 and pass 2 —
    not before the first attempt and not between every attempt."""
    sleeps = []
    monkeypatch.setattr(yt, "_RETRY_PASS_SLEEP_SECONDS", 5)
    monkeypatch.setattr(yt.time, "sleep", lambda s: sleeps.append(s))
    calls = []

    def fake_run(argv, **kwargs):
        calls.append(argv)
        # Sleep must have fired before the 5th call (first pass-2
        # attempt) and never before it.
        if len(calls) < 5:
            assert sleeps == []
        raise RuntimeError(f"yt-dlp failed: {BOT_CHECK}")

    monkeypatch.setattr(yt, "_run_yt_dlp", fake_run)
    with pytest.raises(RuntimeError):
        yt.download("https://www.youtube.com/watch?v=dQw4w9WgXcQ", False,
                    out_dir=str(tmp_path / "req"))
    assert sleeps == [5]
    assert len(calls) == 7


def test_web_attempts_carry_js_runtime_flags(monkeypatch, tmp_path):
    """Web-client attempts name node explicitly (--no-js-runtimes
    BEFORE --js-runtimes node: yt-dlp enables only deno by default).
    Non-web attempts carry no JS-runtime flags."""
    calls = []

    def fake_run(argv, **kwargs):
        calls.append(argv)
        raise RuntimeError(f"yt-dlp failed: {BOT_CHECK}")

    monkeypatch.setattr(yt, "_run_yt_dlp", fake_run)
    with pytest.raises(RuntimeError):
        yt.download("https://www.youtube.com/watch?v=dQw4w9WgXcQ", False,
                    out_dir=str(tmp_path / "req"))
    assert len(calls) == 7
    for i, c in enumerate(calls):
        extractor = _extractor_values(c)
        is_web = extractor == ["youtube:player_client=web",
                               "youtube:player_skip=configs"]
        if is_web:
            assert c.index("--no-js-runtimes") < c.index("--js-runtimes")
            assert c[c.index("--js-runtimes") + 1] == "node"
        else:
            assert "--js-runtimes" not in c
            assert "--no-js-runtimes" not in c
    assert sum("--js-runtimes" in c for c in calls) == 1  # only web+skip


def test_download_cookies_attempt_is_last_only(monkeypatch, tmp_path):
    """When cookies ARE configured they are used exactly once, on the
    final attempt, with the web client — never on the no-cookies chain."""
    cookies = tmp_path / "cookies.txt"
    cookies.write_text(FAKE_COOKIES)
    monkeypatch.setenv("YT_COOKIES_FILE", str(cookies))
    target = tmp_path / "video.mp4"
    target.write_bytes(b"x" * 10)
    calls = []
    attempts = [RuntimeError(f"yt-dlp failed: {BOT_CHECK}")] * 7 + [
        SimpleNamespace(stdout=str(target) + "\n", stderr="", returncode=0)]

    def fake_run(argv, **kwargs):
        calls.append(argv)
        outcome = attempts.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    monkeypatch.setattr(yt, "_run_yt_dlp", fake_run)
    assert yt.download(
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ", False,
        out_dir=str(tmp_path / "req")) == str(target)
    assert len(calls) == 8
    assert all("--cookies" not in c for c in calls[:7])
    last = calls[7]
    assert last[last.index("--cookies") + 1] == str(cookies)
    assert _extractor_values(last) == ["youtube:player_client=web",
                                        "youtube:player_skip=configs"]


# --- fallback chain: resolve ----------------------------------------------

def test_resolve_query_retries_next_client(monkeypatch):
    calls = []
    canned = json.dumps({"id": "abc123", "title": "t", "duration": 10})

    def fake_run(argv, **kwargs):
        calls.append(argv)
        if len(calls) == 1:
            raise RuntimeError(f"yt-dlp failed: {BOT_CHECK}")
        return SimpleNamespace(stdout=canned, stderr="", returncode=0)

    monkeypatch.setattr(yt, "_run_yt_dlp", fake_run)
    out = yt.resolve_query("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
    assert out["video_id"] == "abc123"
    assert len(calls) == 2
    extractors = [_extractor_values(c) for c in calls]
    assert extractors[0] == ["youtube:player_client=android"]
    assert extractors[1] == ["youtube:player_client=android",
                             "youtube:player_skip=configs"]


def test_resolve_query_exhaustion_message(monkeypatch):
    monkeypatch.setattr(yt, "_run_yt_dlp", _bot_check_failure)
    with pytest.raises(RuntimeError) as excinfo:
        yt.resolve_query("مروان موسي الخلاصه")
    assert "all 4 resolve attempts failed" in str(excinfo.value)
    assert "Sign in to confirm" in str(excinfo.value)
    assert _download_error_hint(excinfo.value) == "يوتيوب رافض الطلب من السيرفر"


def test_is_bot_check_error():
    assert yt._is_bot_check_error("Sign in to confirm you're not a bot")
    assert yt._is_bot_check_error("ERROR: 403 Forbidden")
    assert yt._is_bot_check_error("failed to extract player response")
    assert not yt._is_bot_check_error("Requested format is not available")
    assert not yt._is_bot_check_error("Private video")
    assert not yt._is_bot_check_error("")


# --- YT_COOKIES_CONTENT -----------------------------------------------------

def test_cookies_content_written_once_with_0600(monkeypatch, tmp_path):
    """Content env var -> file written once under data/, mode 0600,
    --cookies passed. A second call with the same content rewrites
    nothing (mtime unchanged)."""
    monkeypatch.setattr(yt, "ROOT", tmp_path)
    monkeypatch.setenv("YT_COOKIES_CONTENT", FAKE_COOKIES)
    args = yt._cookies_args()
    assert len(args) == 2 and args[0] == "--cookies"
    written = tmp_path / "data" / "youtube_cookies.txt"
    assert args[1] == str(written)
    assert written.read_text(encoding="utf-8") == FAKE_COOKIES
    assert stat.S_IMODE(os.stat(written).st_mode) == 0o600
    mtime = os.stat(written).st_mtime_ns
    assert yt._cookies_args() == args
    assert os.stat(written).st_mtime_ns == mtime


def test_cookies_content_rewritten_when_content_changes(monkeypatch, tmp_path):
    monkeypatch.setattr(yt, "ROOT", tmp_path)
    monkeypatch.setenv("YT_COOKIES_CONTENT", FAKE_COOKIES)
    yt._cookies_args()
    written = tmp_path / "data" / "youtube_cookies.txt"
    new_content = FAKE_COOKIES.replace("fake-value-123", "fake-value-456")
    monkeypatch.setenv("YT_COOKIES_CONTENT", new_content)
    yt._cookies_args()
    assert written.read_text(encoding="utf-8") == new_content


def test_cookies_file_takes_precedence_over_content(monkeypatch, tmp_path):
    """YT_COOKIES_FILE wins; the content file is never even created."""
    monkeypatch.setattr(yt, "ROOT", tmp_path)
    cookies = tmp_path / "cookies.txt"
    cookies.write_text(FAKE_COOKIES)
    monkeypatch.setenv("YT_COOKIES_FILE", str(cookies))
    monkeypatch.setenv("YT_COOKIES_CONTENT", FAKE_COOKIES)
    assert yt._cookies_args() == ["--cookies", str(cookies)]
    assert not (tmp_path / "data" / "youtube_cookies.txt").exists()


def test_cookies_content_empty_or_unset(monkeypatch, tmp_path):
    monkeypatch.setattr(yt, "ROOT", tmp_path)
    assert yt._cookies_args() == []
    monkeypatch.setenv("YT_COOKIES_CONTENT", "")
    assert yt._cookies_args() == []
    monkeypatch.setenv("YT_COOKIES_CONTENT", "   \n  ")
    assert yt._cookies_args() == []
    assert not (tmp_path / "data" / "youtube_cookies.txt").exists()


def test_cookie_content_never_logged(monkeypatch, tmp_path, caplog):
    """The cookie VALUE must never appear in any log record — not from
    _cookies_args(), and not from the per-attempt failure warnings of
    a download that exhausts the chain while cookies are configured."""
    monkeypatch.setattr(yt, "ROOT", tmp_path)
    monkeypatch.setenv("YT_COOKIES_CONTENT", FAKE_COOKIES)
    secret = "FAKE_COOKIE_SECRET_xyz"
    with caplog.at_level(logging.WARNING, logger="tools.youtube"):
        yt._cookies_args()
        monkeypatch.setattr(yt, "_run_yt_dlp", _bot_check_failure)
        with pytest.raises(RuntimeError):
            yt.download("https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                        False, out_dir=str(tmp_path / "req"))
    assert secret not in caplog.text
    assert "fake-value-123" not in caplog.text
