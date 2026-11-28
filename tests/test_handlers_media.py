"""Media flow: search -> one download attempt -> send, or in-character
fallback with link + open-source alternatives."""
from pathlib import Path

from bahgat import media
from bahgat.handlers import media as media_handler

from conftest import FakeLLM, make_context, make_update


async def run(update_text, ctx):
    u = make_update(update_text)
    await media_handler.handle(u, ctx, update_text)
    return u


def sent_texts(update):
    return [p for k, p, _kw in update.effective_message.sent if k == "text"]


class TestDirectUrl:
    async def test_download_success_sends_audio(self, tmp_data, tmp_path,
                                                monkeypatch):
        fake_file = tmp_path / "dl" / "x.mp3"
        fake_file.parent.mkdir(parents=True)
        fake_file.write_bytes(b"audio bytes")

        async def fake_dl(url, audio_only=False, out_dir=None):
            return fake_file

        monkeypatch.setattr(media, "adownload_once", fake_dl)
        u = await run("بهجت نزل https://www.youtube.com/watch?v=abc",
                      make_context(llm_client=FakeLLM()))
        kinds = [k for k, _p, _kw in u.effective_message.sent]
        assert kinds == ["audio"]
        assert not fake_file.exists()  # cleaned up

    async def test_download_failure_falls_back(self, tmp_data, monkeypatch):
        async def boom(url, audio_only=False, out_dir=None):
            raise media.DownloadError("Sign in to confirm you're not a bot")

        async def alts(query, n=2):
            return [{"title": "نسخة مفتوحة", "source": "Internet Archive",
                     "url": "https://archive.org/details/x"}]

        monkeypatch.setattr(media, "adownload_once", boom)
        monkeypatch.setattr(media, "asearch_open_sources", alts)
        u = await run("بهجت نزل https://www.youtube.com/watch?v=abc",
                      make_context(llm_client=FakeLLM()))
        replies = sent_texts(u)
        assert len(replies) == 1
        assert "https://www.youtube.com/watch?v=abc" in replies[0]  # the link
        assert "archive.org/details/x" in replies[0]                # the fallback

    async def test_video_requested_sends_video(self, tmp_data, tmp_path,
                                               monkeypatch):
        fake_file = tmp_path / "dl" / "x.mp4"
        fake_file.parent.mkdir(parents=True)
        fake_file.write_bytes(b"video bytes")

        async def fake_dl(url, audio_only=False, out_dir=None):
            assert audio_only is False
            return fake_file

        monkeypatch.setattr(media, "adownload_once", fake_dl)
        u = await run("بهجت هات الفيديو https://www.youtube.com/watch?v=abc",
                      make_context(llm_client=FakeLLM()))
        kinds = [k for k, _p, _kw in u.effective_message.sent]
        assert kinds == ["video"]


class TestQueryFlow:
    async def test_query_resolves_then_downloads(self, tmp_data, tmp_path,
                                                 monkeypatch):
        fake_file = tmp_path / "dl" / "x.mp3"
        fake_file.parent.mkdir(parents=True)
        fake_file.write_bytes(b"audio")

        async def fake_search(query, limit=5):
            assert "ويجز" in query
            return [{"id": "abc", "title": "ويجز - تراك",
                     "url": "https://www.youtube.com/watch?v=abc",
                     "duration": 200}]

        async def fake_dl(url, audio_only=False, out_dir=None):
            return fake_file

        monkeypatch.setattr(media, "asearch_youtube", fake_search)
        monkeypatch.setattr(media, "adownload_once", fake_dl)
        u = await run("بهجت شغل اغنية ويجز", make_context(llm_client=FakeLLM()))
        kinds = [k for k, _p, _kw in u.effective_message.sent]
        assert kinds == ["audio"]

    async def test_search_blocked_goes_open_source(self, tmp_data, monkeypatch):
        async def no_results(query, limit=5):
            return []

        async def alts(query, n=2):
            return [{"title": "من ساوندكلاود", "source": "SoundCloud",
                     "url": "https://soundcloud.com/x"}]

        monkeypatch.setattr(media, "asearch_youtube", no_results)
        monkeypatch.setattr(media, "asearch_open_sources", alts)
        u = await run("بهجت شغل اغنية ويجز", make_context(llm_client=FakeLLM()))
        replies = sent_texts(u)
        assert "soundcloud.com/x" in replies[0]

    async def test_nothing_found_anywhere(self, tmp_data, monkeypatch):
        async def no_results(query, limit=5):
            return []

        async def no_alts(query, n=2):
            return []

        monkeypatch.setattr(media, "asearch_youtube", no_results)
        monkeypatch.setattr(media, "asearch_open_sources", no_alts)
        u = await run("بهجت شغل اغنية كلامفهم", make_context(llm_client=FakeLLM()))
        assert "متأكد من الاسم" in sent_texts(u)[0]

    async def test_no_query_asks_for_name(self, tmp_data):
        u = await run("بهجت شغل اغنية", make_context(llm_client=FakeLLM()))
        assert "قولي اسم" in sent_texts(u)[0]


class TestCleanup:
    async def test_temp_dir_removed_after_send(self, tmp_data, tmp_path,
                                               monkeypatch):
        dl_dir = tmp_path / "downloads" / "abc123"
        dl_dir.mkdir(parents=True)
        fake_file = dl_dir / "x.mp3"
        fake_file.write_bytes(b"audio")

        async def fake_dl(url, audio_only=False, out_dir=None):
            return fake_file

        monkeypatch.setattr(media, "adownload_once", fake_dl)
        await run("بهجت نزل https://www.youtube.com/watch?v=abc",
                  make_context(llm_client=FakeLLM()))
        assert not dl_dir.exists()
        assert Path(tmp_path / "downloads").exists()  # parent kept
