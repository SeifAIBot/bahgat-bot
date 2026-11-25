"""Argument-injection tests for tools/youtube.py (v0.5 Workstream A).

subprocess.run is mocked everywhere — no network and no yt-dlp binary
required. The missing-binary path is covered by making the mock raise
FileNotFoundError.
"""
import json
from types import SimpleNamespace

import pytest

from tools.youtube import ALLOWED_HOSTS, download, resolve_query, validate_youtube_url

EVIL_INPUTS = [
    "--exec curl x | sh",
    "-h",
    "--config-location /etc/passwd",
    "https://evil.com/v?v=1",
    "https://youtube.com.evil.com/",
    "http://www.youtube.com/watch?v=x",
    "https://www.youtube.com.evil.com/watch?v=x",
]

GOOD_URLS = [
    "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
    "https://youtu.be/dQw4w9WgXcQ",
    "https://music.youtube.com/watch?v=x",
    "https://youtube.com/watch?v=x",
]


def test_allowed_hosts():
    assert ALLOWED_HOSTS == {
        "youtube.com", "www.youtube.com", "youtu.be", "music.youtube.com",
    }


@pytest.mark.parametrize("url", GOOD_URLS)
def test_validate_youtube_url_accepts(url):
    assert validate_youtube_url(url) == url


@pytest.mark.parametrize("bad", EVIL_INPUTS)
def test_validate_youtube_url_rejects(bad):
    with pytest.raises(ValueError):
        validate_youtube_url(bad)


@pytest.mark.parametrize("bad", EVIL_INPUTS)
def test_resolve_query_rejects(bad):
    with pytest.raises(ValueError):
        resolve_query(bad)


@pytest.mark.parametrize("bad", EVIL_INPUTS)
def test_download_rejects(bad, monkeypatch):
    def _no_run(*args, **kwargs):
        raise AssertionError("subprocess.run must not be called for evil input")

    monkeypatch.setattr("tools.youtube.subprocess.run", _no_run)
    with pytest.raises(ValueError):
        download(bad, False, out_dir="/tmp/never-created-yt-test")


CANNED_JSON = json.dumps({
    "id": "abc123",
    "title": "فيديو تجريبي",
    "duration": 123,
    "filesize_approx": 456789,
    "webpage_url": "https://www.youtube.com/watch?v=abc123",
})


def test_resolve_query_arabic_text_builds_ytsearch(monkeypatch):
    seen = {}

    def fake_run(argv, **kwargs):
        seen["argv"] = argv
        return SimpleNamespace(stdout=CANNED_JSON, stderr="", returncode=0)

    monkeypatch.setattr("tools.youtube.subprocess.run", fake_run)
    result = resolve_query("بهجت صابر مضحك")
    argv = seen["argv"]
    assert "ytsearch1:بهجت صابر مضحك" in argv
    assert "--" in argv
    # "--" immediately before the ytsearch argument; raw text is never bare.
    assert argv[argv.index("--") + 1] == "ytsearch1:بهجت صابر مضحك"
    assert "--dump-single-json" in argv and "--no-playlist" in argv
    assert result == {
        "video_id": "abc123",
        "url": "https://www.youtube.com/watch?v=abc123",
        "title": "فيديو تجريبي",
        "duration": 123,
        "approx_size": 456789,
    }


def test_resolve_query_url_uses_url_directly(monkeypatch):
    seen = {}

    def fake_run(argv, **kwargs):
        seen["argv"] = argv
        return SimpleNamespace(stdout=CANNED_JSON, stderr="", returncode=0)

    monkeypatch.setattr("tools.youtube.subprocess.run", fake_run)
    result = resolve_query("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
    argv = seen["argv"]
    assert not any(a.startswith("ytsearch") for a in argv)
    assert argv[argv.index("--") + 1] == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    assert result["video_id"] == "abc123"


def test_resolve_query_missing_ytdlp_raises_runtime_error(monkeypatch):
    def fake_run(argv, **kwargs):
        raise FileNotFoundError(2, "No such file or directory", "yt-dlp")

    monkeypatch.setattr("tools.youtube.subprocess.run", fake_run)
    with pytest.raises(RuntimeError, match="yt-dlp is not installed"):
        resolve_query("بهجت صابر")


def test_download_argv_has_dashdash_before_url(monkeypatch, tmp_path):
    target = tmp_path / "video.mp4"
    target.write_bytes(b"x" * 10)
    seen = {}

    def fake_run(argv, **kwargs):
        seen["argv"] = argv
        return SimpleNamespace(stdout=str(target) + "\n", stderr="", returncode=0)

    monkeypatch.setattr("tools.youtube.subprocess.run", fake_run)
    out_dir = tmp_path / "req"
    url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    assert download(url, False, out_dir=str(out_dir)) == str(target)
    assert out_dir.is_dir()  # out_dir is honoured (round-4 N3)
    argv = seen["argv"]
    assert argv[-2] == "--" and argv[-1] == url
    assert "--no-playlist" in argv and "--max-filesize" in argv


def test_download_plain_query_resolves_first(monkeypatch, tmp_path):
    target = tmp_path / "audio.mp3"
    target.write_bytes(b"y" * 10)
    calls = []

    def fake_run(argv, **kwargs):
        calls.append(argv)
        if "--dump-single-json" in argv:
            return SimpleNamespace(stdout=CANNED_JSON, stderr="", returncode=0)
        return SimpleNamespace(stdout=str(target) + "\n", stderr="", returncode=0)

    monkeypatch.setattr("tools.youtube.subprocess.run", fake_run)
    assert download("بهجت صابر مضحك", True, out_dir=str(tmp_path / "req")) == str(target)
    assert len(calls) == 2
    assert any(a.startswith("ytsearch1:") for a in calls[0])
    assert calls[1][-2] == "--"
    assert calls[1][-1] == "https://www.youtube.com/watch?v=abc123"
