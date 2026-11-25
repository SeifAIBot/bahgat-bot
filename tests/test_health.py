"""Health endpoint (tg/health.py) + BAHGAT_DATA_DIR wiring.

The health server is what a PaaS (Northflank) probes: GET /healthz (and
/health) must be 200 while the polling loop is alive and 503 when the
heartbeat is stale/missing. Server is stdlib-only, started from main.py.
"""
import json
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from core.config import data_dir
from tg.health import resolve_port, start_health_server, stop_health_server

ROOT = Path(__file__).resolve().parents[1]


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _get(port: int, path: str) -> tuple[int, dict]:
    """GET a path; returns (status, parsed JSON body) even for 4xx/5xx."""
    try:
        with urllib.request.urlopen(
            f"http://127.0.0.1:{port}{path}", timeout=5
        ) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


@pytest.fixture
def heartbeat(tmp_path):
    """A heartbeat.json path; write fresh/stale payloads into it."""
    path = tmp_path / "heartbeat.json"

    def _write(age_seconds: float | None):
        if age_seconds is None:
            return
        path.write_text(
            json.dumps({"last_poll": time.time() - age_seconds, "last_reply": None}),
            encoding="utf-8",
        )

    _write.fresh = lambda: _write(10)
    _write.stale = lambda: _write(400)
    _write.missing = lambda: None  # never write the file
    return path, _write


@pytest.fixture
def server(heartbeat):
    """Start a health server on an ephemeral port; stop it after the test."""
    path, _ = heartbeat
    srv = start_health_server(heartbeat_path=path, port=0)
    yield srv
    stop_health_server(srv)


def test_healthz_200_fresh_heartbeat(server, heartbeat):
    _, write = heartbeat
    write.fresh()
    status, body = _get(server.server_address[1], "/healthz")
    assert status == 200
    assert body["status"] == "ok"
    assert 0 <= body["last_poll_age_seconds"] < 300


def test_health_alias_200(server, heartbeat):
    _, write = heartbeat
    write.fresh()
    status, body = _get(server.server_address[1], "/health")
    assert status == 200
    assert body["status"] == "ok"


def test_healthz_503_stale_heartbeat(server, heartbeat):
    _, write = heartbeat
    write.stale()
    status, body = _get(server.server_address[1], "/healthz")
    assert status == 503
    assert body["status"] == "unavailable"
    assert body["last_poll_age_seconds"] >= 300


def test_healthz_503_missing_heartbeat(server, heartbeat):
    _, write = heartbeat
    write.missing()
    status, body = _get(server.server_address[1], "/healthz")
    assert status == 503
    assert body["status"] == "unavailable"
    assert body["last_poll_age_seconds"] is None


def test_unknown_path_404(server, heartbeat):
    _, write = heartbeat
    write.fresh()
    status, body = _get(server.server_address[1], "/nope")
    assert status == 404
    assert body["status"] == "not_found"


def test_binds_port_env(monkeypatch, tmp_path):
    """The server binds the $PORT env value when no port is passed."""
    port = _free_port()
    monkeypatch.setenv("PORT", str(port))
    assert resolve_port() == port
    srv = start_health_server(heartbeat_path=tmp_path / "heartbeat.json")
    try:
        assert srv.server_address[1] == port
        status, _ = _get(port, "/healthz")
        assert status == 503  # no heartbeat file yet
    finally:
        stop_health_server(srv)


def test_data_dir_env_override(monkeypatch, tmp_path):
    """BAHGAT_DATA_DIR redirects the runtime state dir (Northflank /data)."""
    monkeypatch.setenv("BAHGAT_DATA_DIR", str(tmp_path))
    assert data_dir() == tmp_path
    monkeypatch.delenv("BAHGAT_DATA_DIR")
    assert data_dir() == ROOT / "data"


def test_data_dir_wiring_subprocess(tmp_path):
    """End-to-end: with BAHGAT_DATA_DIR set before process start, every
    module that touches the DB resolves under the override dir. This is
    the wiring the Northflank persistent volume depends on."""
    override = tmp_path / "volume"
    override.mkdir()
    code = (
        "import json;"
        "from brain.memory import DB_PATH as m;"
        "from tg.handlers import DB_PATH as h;"
        "from tg.app import DATA_DIR;"
        "from brain.router import BrainRouter;"
        "import types;"
        "r = BrainRouter(types.SimpleNamespace());"
        "print(json.dumps({'memory': str(m), 'handlers': str(h),"
        " 'app_data': str(DATA_DIR), 'router': str(r.db)}))"
    )
    env = {"BAHGAT_DATA_DIR": str(override), "PATH": "/usr/bin:/bin:/usr/local/bin"}
    proc = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        cwd=ROOT,
        env={**env, "PYTHONPATH": str(ROOT)},
        timeout=60,
    )
    assert proc.returncode == 0, proc.stderr
    paths = json.loads(proc.stdout)
    for value in paths.values():
        assert value.startswith(str(override)), paths
    assert paths["memory"].endswith("bahgat.db")
    assert paths["handlers"].endswith("bahgat.db")
    assert paths["router"].endswith("bahgat.db")
