"""Light voice tests for tools/voice.py (v0.5 Workstream A).

edge_tts is NOT installed in this VM's .venv, so it is stubbed in
sys.modules before importing tools.voice. The stub's Communicate.save
writes a partial .mp3 and then either succeeds or raises, letting us
check partial-file cleanup without any network or ffmpeg binary.
"""
import os
import subprocess
import sys
import types

import pytest


class _FakeCommunicate:
    mode = "fail"  # "fail" | "ok"

    def __init__(self, text, voice, **kwargs):
        self.text = text

    async def save(self, path):
        with open(path, "wb") as f:
            f.write(b"partial-mp3")
        if _FakeCommunicate.mode == "fail":
            raise RuntimeError("TTS boom")


_stub = types.ModuleType("edge_tts")
_stub.Communicate = _FakeCommunicate
sys.modules.setdefault("edge_tts", _stub)

from tools.voice import synthesize  # noqa: E402


def test_synthesize_failure_cleans_up_partial_files(tmp_path):
    _FakeCommunicate.mode = "fail"
    out = tmp_path / "voice"
    with pytest.raises(RuntimeError, match="TTS boom"):
        import asyncio

        asyncio.run(synthesize("اهلا يا بهجت", out_dir=str(out)))
    assert list(out.iterdir()) == [], "no .mp3/.ogg partials may be left behind"


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
