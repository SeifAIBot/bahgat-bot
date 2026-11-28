"""Voice: TTS text cleaning, synthesis failure propagation, send fallback."""
import sys
from types import SimpleNamespace

import pytest

from bahgat import voice
from bahgat.handlers import voice as voice_handler

from conftest import make_update


class TestCleanForTts:
    def test_strips_links_and_markdown(self):
        out = voice.clean_for_tts("خد اللينك https://x.com/a **مهم** [1]")
        assert "https://" not in out
        assert "**" not in out
        assert "[1]" not in out
        assert "مهم" in out

    def test_length_cap(self):
        out = voice.clean_for_tts("كلمة " * 500, max_chars=100)
        assert len(out) <= 100


class _FailingCommunicate:
    def __init__(self, text, voice_name, **kw):
        pass

    async def save(self, path):
        raise RuntimeError("tts down")


class TestSynthesize:
    async def test_failure_raises_and_cleans_up(self, monkeypatch, tmp_path):
        monkeypatch.setitem(sys.modules, "edge_tts",
                            SimpleNamespace(Communicate=_FailingCommunicate))
        with pytest.raises(RuntimeError):
            await voice.synthesize("اهلا", out_dir=tmp_path)
        assert list(tmp_path.iterdir()) == []  # no partial files left


class TestSendVoiceReply:
    async def test_falls_back_to_text_on_failure(self, monkeypatch):
        async def boom(text, out_dir=None, rvc_url=""):
            raise RuntimeError("tts down")

        monkeypatch.setattr(voice, "send_voice", boom)
        update = make_update("قولها بصوت")
        await voice_handler.send_voice_reply(update, "الرد النصي")
        kinds = [k for k, _p, _kw in update.effective_message.sent]
        assert kinds == [("text")]
        assert update.effective_message.sent[0][1] == "الرد النصي"

    async def test_sends_voice_on_success(self, monkeypatch, tmp_path):
        ogg = tmp_path / "x.ogg"
        ogg.write_bytes(b"OggS fake")

        async def ok(text, out_dir=None, rvc_url=""):
            return ogg

        monkeypatch.setattr(voice, "send_voice", ok)
        update = make_update("قولها بصوت")
        await voice_handler.send_voice_reply(update, "الرد النصي")
        kinds = [k for k, _p, _kw in update.effective_message.sent]
        assert kinds == [("voice")]
        assert not ogg.exists()  # cleaned up after sending


class TestRvcSeam:
    """send_voice(): RVC worker first when configured, Edge TTS fallback."""

    async def test_uses_rvc_when_configured(self, monkeypatch, tmp_path):
        mp3 = tmp_path / "in.mp3"
        mp3.write_bytes(b"fake mp3")
        rvc_ogg = tmp_path / "rvc.ogg"
        rvc_ogg.write_bytes(b"OggS rvc")

        async def fake_mp3(text, out_dir=None):
            return mp3

        async def fake_rvc(mp3_path, url, timeout=90):
            assert url == "http://rvc:8000"
            return rvc_ogg

        monkeypatch.setattr(voice, "_edge_mp3", fake_mp3)
        monkeypatch.setattr(voice, "_convert_via_rvc", fake_rvc)
        out = await voice.send_voice("اهلا", out_dir=tmp_path,
                                     rvc_url="http://rvc:8000")
        assert out == rvc_ogg

    async def test_rvc_failure_falls_back_to_edge(self, monkeypatch, tmp_path):
        mp3 = tmp_path / "in.mp3"
        mp3.write_bytes(b"fake mp3")
        edge_ogg = tmp_path / "edge.ogg"
        edge_ogg.write_bytes(b"OggS edge")

        async def fake_mp3(text, out_dir=None):
            return mp3

        async def boom(mp3_path, url, timeout=90):
            raise RuntimeError("worker down")

        async def fake_edge(text, out_dir=None):
            return edge_ogg

        monkeypatch.setattr(voice, "_edge_mp3", fake_mp3)
        monkeypatch.setattr(voice, "_convert_via_rvc", boom)
        monkeypatch.setattr(voice, "synthesize", fake_edge)
        out = await voice.send_voice("اهلا", out_dir=tmp_path,
                                     rvc_url="http://rvc:8000")
        assert out == edge_ogg

    async def test_no_rvc_url_never_touches_worker(self, monkeypatch, tmp_path):
        edge_ogg = tmp_path / "edge.ogg"
        edge_ogg.write_bytes(b"OggS edge")

        async def fake_edge(text, out_dir=None):
            return edge_ogg

        async def boom(mp3_path, url, timeout=90):
            raise AssertionError("RVC must not be called without RVC_URL")

        monkeypatch.setattr(voice, "synthesize", fake_edge)
        monkeypatch.setattr(voice, "_convert_via_rvc", boom)
        out = await voice.send_voice("اهلا", out_dir=tmp_path, rvc_url="")
        assert out == edge_ogg
