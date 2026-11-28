"""Media: URL validation, query cleaning, one-shot download, fallbacks."""
import json
from types import SimpleNamespace

import pytest

from bahgat import media
from bahgat.handlers import media as media_handler


class TestValidateYoutubeUrl:
    def test_ok(self):
        assert media.validate_youtube_url("https://www.youtube.com/watch?v=abc")
        assert media.validate_youtube_url("https://youtu.be/abc")
        assert media.validate_youtube_url("https://music.youtube.com/watch?v=abc")

    def test_rejects(self):
        for bad in ("", "http://www.youtube.com/watch?v=abc",
                    "https://evil.com/watch?v=abc", "-x",
                    "https://user:pass@youtube.com/watch?v=abc",
                    "not a url"):
            with pytest.raises(ValueError):
                media.validate_youtube_url(bad)


class TestExtractAndQuery:
    def test_extract_url(self):
        u = media_handler.extract_youtube_url(
            "بهجت شغل ده https://www.youtube.com/watch?v=abc123 بسرعة")
        assert u == "https://www.youtube.com/watch?v=abc123"

    def test_extract_url_ignores_non_youtube(self):
        assert media_handler.extract_youtube_url("بص https://evil.com/x") is None

    def test_query_from_text(self):
        q = media_handler.query_from_text("بهجت شغل اغنية ويجز الجديدة")
        assert "ويجز" in q
        assert "الجديدة" in q
        for noise in ("بهجت", "شغل", "اغنية"):
            assert noise not in q.split()

    def test_wants_video(self):
        assert media_handler.wants_video("هات الفيديو")
        assert not media_handler.wants_video("هات الاغنية")


class TestSearchYoutube:
    def test_parses_entries(self, monkeypatch):
        payload = {"entries": [
            {"id": "abc", "title": "أغنية حلوة", "duration": 200},
            {"id": "def", "title": "تراك تاني", "duration": 180},
        ]}
        monkeypatch.setattr(media, "_run_yt_dlp",
                            lambda args, timeout: SimpleNamespace(
                                stdout=json.dumps(payload)))
        out = media.search_youtube("ويجز")
        assert len(out) == 2
        assert out[0]["url"] == "https://www.youtube.com/watch?v=abc"
        assert out[0]["title"] == "أغنية حلوة"

    def test_failure_returns_empty(self, monkeypatch):
        def boom(args, timeout):
            raise media.DownloadError("blocked")

        monkeypatch.setattr(media, "_run_yt_dlp", boom)
        assert media.search_youtube("ويجز") == []

    def test_empty_query(self):
        assert media.search_youtube("") == []


class TestDownloadOnce:
    def test_success_returns_file(self, monkeypatch, tmp_path):
        def fake_run(args, timeout):
            out_tmpl = args[args.index("-o") + 1]
            path = out_tmpl.replace("%(id)s", "vid1").replace("%(ext)s", "mp3")
            with open(path, "wb") as fh:
                fh.write(b"x" * 100)
            return SimpleNamespace(stdout="", returncode=0)

        monkeypatch.setattr(media, "_run_yt_dlp", fake_run)
        out = media.download_once("https://www.youtube.com/watch?v=vid1",
                                  audio_only=True, out_dir=tmp_path)
        assert out.exists() and out.stat().st_size == 100

    def test_single_attempt_no_retry(self, monkeypatch, tmp_path):
        calls = []

        def boom(args, timeout):
            calls.append(args)
            raise media.DownloadError("Sign in to confirm you're not a bot")

        monkeypatch.setattr(media, "_run_yt_dlp", boom)
        with pytest.raises(media.DownloadError):
            media.download_once("https://www.youtube.com/watch?v=vid1",
                                out_dir=tmp_path)
        assert len(calls) == 1  # ONE attempt — no retries, no proxy dance

    def test_no_file_is_error(self, monkeypatch, tmp_path):
        monkeypatch.setattr(media, "_run_yt_dlp",
                            lambda args, timeout: SimpleNamespace(stdout=""))
        with pytest.raises(media.DownloadError):
            media.download_once("https://www.youtube.com/watch?v=vid1",
                                out_dir=tmp_path)


class TestOpenSources:
    def test_archive_results(self, monkeypatch):
        payload = {"response": {"docs": [
            {"identifier": "song1", "title": "أغنية مفتوحة"},
        ]}}

        class FakeResp:
            def read(self):
                return json.dumps(payload).encode()

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        monkeypatch.setattr(media.urllib.request, "urlopen",
                            lambda req, timeout=None: FakeResp())
        out = media.search_internet_archive("موسيقى")
        assert out == [{"title": "أغنية مفتوحة",
                        "url": "https://archive.org/details/song1",
                        "source": "Internet Archive"}]

    def test_archive_failure_empty(self, monkeypatch):
        def boom(req, timeout=None):
            raise OSError("no network")

        monkeypatch.setattr(media.urllib.request, "urlopen", boom)
        assert media.search_internet_archive("موسيقى") == []

    def test_search_open_sources_never_raises(self, monkeypatch):
        monkeypatch.setattr(media, "search_internet_archive",
                            lambda q, n=2: [])
        monkeypatch.setattr(media, "_search_extractor",
                            lambda p, q, s, n: [])
        assert media.search_open_sources("أغنية") == []


class TestFallbackMessage:
    def test_contains_link_and_alternatives(self):
        alts = [{"title": "أغنية", "url": "https://archive.org/details/x",
                 "source": "Internet Archive"}]
        msg = media_handler.format_fallback_message(
            "https://www.youtube.com/watch?v=abc", alts)
        assert "https://www.youtube.com/watch?v=abc" in msg
        assert "https://archive.org/details/x" in msg
        assert "Internet Archive" in msg

    def test_fallback_labelled_as_different_catalogue(self):
        # Honest label (expert §6): open sources are NOT the same song.
        alts = [{"title": "أغنية", "url": "https://archive.org/details/x",
                 "source": "Internet Archive"}]
        msg = media_handler.format_fallback_message(
            "https://www.youtube.com/watch?v=abc", alts)
        assert "مش نفس الأغنية بالضرورة" in msg


class TestProxy:
    """YTDLP_PROXY_URL (e.g. a WARP wireproxy) is honoured by yt-dlp,
    non-fatal when unset."""

    def test_proxy_args_empty_by_default(self, monkeypatch):
        monkeypatch.delenv("YTDLP_PROXY_URL", raising=False)
        assert media._proxy_args() == []

    def test_proxy_args_from_env(self, monkeypatch):
        monkeypatch.setenv("YTDLP_PROXY_URL", "socks5://127.0.0.1:1080")
        assert media._proxy_args() == ["--proxy", "socks5://127.0.0.1:1080"]

    def test_run_yt_dlp_includes_proxy(self, monkeypatch):
        monkeypatch.setenv("YTDLP_PROXY_URL", "socks5://127.0.0.1:1080")
        seen = {}

        def fake_run(cmd, **kw):
            seen["cmd"] = cmd
            return SimpleNamespace(returncode=0, stdout="{}", stderr="")

        monkeypatch.setattr(media.subprocess, "run", fake_run)
        media._run_yt_dlp(["--version"], timeout=5)
        assert "--proxy" in seen["cmd"]
        assert "socks5://127.0.0.1:1080" in seen["cmd"]

    def test_run_yt_dlp_without_proxy(self, monkeypatch):
        monkeypatch.delenv("YTDLP_PROXY_URL", raising=False)
        seen = {}

        def fake_run(cmd, **kw):
            seen["cmd"] = cmd
            return SimpleNamespace(returncode=0, stdout="{}", stderr="")

        monkeypatch.setattr(media.subprocess, "run", fake_run)
        media._run_yt_dlp(["--version"], timeout=5)
        assert "--proxy" not in seen["cmd"]
