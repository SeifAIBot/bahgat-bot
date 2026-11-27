"""Light voice tests for tools/voice.py (v0.5 Workstream A).

edge_tts is stubbed in sys.modules before importing tools.voice, so no
test touches the network. The stub's Communicate.save writes a partial
.mp3 and then either succeeds or raises, letting us check the retry
path and partial-file cleanup without any network or ffmpeg binary.
"""
import os
import subprocess
import sys
import types

import pytest


class _FakeCommunicate:
    mode = "fail"  # "fail" | "ok" | "fail_once"
    calls = 0

    def __init__(self, text, voice, **kwargs):
        self.text = text

    async def save(self, path):
        _FakeCommunicate.calls += 1
        with open(path, "wb") as f:
            f.write(b"partial-mp3")
        if _FakeCommunicate.mode == "fail":
            raise RuntimeError("TTS boom")
        if _FakeCommunicate.mode == "fail_once" and _FakeCommunicate.calls == 1:
            raise RuntimeError("TTS boom once")


_stub = types.ModuleType("edge_tts")
_stub.Communicate = _FakeCommunicate
sys.modules.setdefault("edge_tts", _stub)

from tools.voice import synthesize  # noqa: E402


def test_synthesize_failure_cleans_up_partial_files(tmp_path):
    _FakeCommunicate.mode = "fail"
    _FakeCommunicate.calls = 0
    out = tmp_path / "voice"
    with pytest.raises(RuntimeError, match="TTS boom"):
        import asyncio

        asyncio.run(synthesize("اهلا يا بهجت", out_dir=str(out)))
    assert list(out.iterdir()) == [], "no .mp3/.ogg partials may be left behind"
    # v1.9: the module itself retries once before giving up.
    assert _FakeCommunicate.calls == 2


def test_synthesize_retries_once_then_succeeds(tmp_path, monkeypatch):
    # v1.9: first handshake fails (the Sec-MS-GEC 403 class of failure),
    # second attempt succeeds — the caller gets its ogg, no partials.
    _FakeCommunicate.mode = "fail_once"
    _FakeCommunicate.calls = 0
    out = tmp_path / "voice"

    def fake_run(argv, **kwargs):
        ogg = argv[-1]
        with open(ogg, "wb") as f:
            f.write(b"fake-ogg")
        return subprocess.CompletedProcess(argv, 0)

    monkeypatch.setattr("tools.voice.subprocess.run", fake_run)
    import asyncio

    ogg = asyncio.run(synthesize("اهلا يا بهجت", out_dir=str(out)))
    assert _FakeCommunicate.calls == 2
    assert ogg.endswith(".ogg")
    assert os.path.exists(ogg)
    leftovers = [p.name for p in out.iterdir()]
    assert leftovers == [os.path.basename(ogg)], f"only ogg may remain, got {leftovers}"


def test_synthesize_success_returns_ogg_and_deletes_mp3(tmp_path, monkeypatch):
    _FakeCommunicate.mode = "ok"
    out = tmp_path / "voice"

    def fake_run(argv, **kwargs):
        # ffmpeg argv: [..., "-i", mp3, "-c:a", "libopus", ogg]
        ogg = argv[-1]
        with open(ogg, "wb") as f:
            f.write(b"fake-ogg")
        return subprocess.CompletedProcess(argv, 0)

    monkeypatch.setattr("tools.voice.subprocess.run", fake_run)
    import asyncio

    ogg = asyncio.run(synthesize("اهلا يا بهجت", out_dir=str(out)))
    assert ogg.endswith(".ogg")
    assert os.path.exists(ogg)
    leftovers = [p.name for p in out.iterdir()]
    assert leftovers == [os.path.basename(ogg)], f"only ogg may remain, got {leftovers}"
