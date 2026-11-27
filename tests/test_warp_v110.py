"""Cloudflare WARP in-container egress (v1.10).

wgcf + wireproxy, profile persisted under data/warp/ (the /app/data
volume), proxy on the yt-dlp DOWNLOAD path only, WARP_ENABLED kill
switch, enrolment cap of 3, proxy-error circuit breaker. No network in
these tests: wgcf/wireproxy/subprocess are stubbed, the SOCKS check is
stubbed, and the trace check is stubbed.
"""
import json
import logging
from types import SimpleNamespace

import pytest

import tools.warp as warp
import tools.youtube as yt


@pytest.fixture(autouse=True)
def _clean_warp_env(monkeypatch, tmp_path):
    """Isolate every test: fresh data dir, no WARP env, no running
    process, breaker untripped."""
    for var in ("WARP_ENABLED", "WARP_REENROLL", "WARP_PROXY_URL"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(warp, "data_dir", lambda: tmp_path)
    monkeypatch.setattr(warp, "_WIREPROXY_PROC", None)
    monkeypatch.setattr(warp, "_WIREPROXY_LOG_HANDLE", None)
    monkeypatch.setattr(yt, "_PROXY_DOWN_UNTIL", 0.0)
    monkeypatch.setattr(yt, "_RETRY_PASS_SLEEP_SECONDS", 0)
    yield
    for var in ("WARP_ENABLED", "WARP_REENROLL", "WARP_PROXY_URL"):
        monkeypatch.delenv(var, raising=False)


def _fake_proc(alive=True):
    calls = {"terminate": 0, "kill": 0}
    proc = SimpleNamespace(
        returncode=None if alive else 0,
        poll=lambda: None if alive else 0,
        terminate=lambda: calls.__setitem__("terminate", 1),
        kill=lambda: calls.__setitem__("kill", 1),
        wait=lambda timeout=None: None,
    )
    proc.calls = calls
    return proc


def _fake_wgcf_success(monkeypatch, tmp_path):
    """wgcf stub: register ok; generate writes the profile file."""
    def fake_run(args, **kwargs):
        if args and args[0] == "generate":
            (tmp_path / "warp" / warp.WGCF_PROFILE_FILE).write_text(
                "[Interface]\nPrivateKey = FAKEKEY\nAddress = 172.16.0.2/32\n"
                "[Peer]\nPublicKey = FAKEPUB\nAllowedIPs = 0.0.0.0/0\n"
                "Endpoint = engage.cloudflareclient.com:2408\n")
        return SimpleNamespace(returncode=0, stdout="", stderr="")
    monkeypatch.setattr(warp, "_run_wgcf", fake_run)


# --- kill switch + proxy URL ------------------------------------------------

def test_warp_enabled_default_on():
    assert warp.warp_enabled() is True


@pytest.mark.parametrize("value", ["0", "false", "False", "no", "off", "OFF"])
def test_warp_enabled_off_values(monkeypatch, value):
    monkeypatch.setenv("WARP_ENABLED", value)
    assert warp.warp_enabled() is False


@pytest.mark.parametrize("value", ["1", "true", "True", "yes", "on"])
def test_warp_enabled_on_values(monkeypatch, value):
    monkeypatch.setenv("WARP_ENABLED", value)
    assert warp.warp_enabled() is True


def test_warp_enabled_garbage_warns_and_stays_on(monkeypatch, caplog):
    monkeypatch.setenv("WARP_ENABLED", "maybe")
    with caplog.at_level(logging.WARNING, logger="tools.warp"):
        assert warp.warp_enabled() is True
    assert "WARP_ENABLED" in caplog.text


def test_proxy_url_default_and_override(monkeypatch):
    assert warp.proxy_url() == "socks5://127.0.0.1:1080"
    monkeypatch.setenv("WARP_PROXY_URL", "socks5://127.0.0.1:9999")
    assert warp.proxy_url() == "socks5://127.0.0.1:9999"
    monkeypatch.setenv("WARP_ENABLED", "0")
    assert warp.proxy_url() is None


# --- proxy_available ---------------------------------------------------------

def test_proxy_available_requires_enabled(monkeypatch):
    monkeypatch.setenv("WARP_ENABLED", "0")
    monkeypatch.setattr(warp, "_socks_connectable", lambda timeout=2.0: True)
    assert warp.proxy_available() is False


def test_proxy_available_requires_process_or_override(monkeypatch):
    """No wireproxy started by us and no external proxy configured:
    even a listening port is not ours to use."""
    monkeypatch.setattr(warp, "_socks_connectable", lambda timeout=2.0: True)
    assert warp.proxy_available() is False


def test_proxy_available_with_live_process(monkeypatch):
    monkeypatch.setattr(warp, "_WIREPROXY_PROC", _fake_proc(alive=True))
    monkeypatch.setattr(warp, "_socks_connectable", lambda timeout=2.0: True)
    assert warp.proxy_available() is True


def test_proxy_available_dead_process(monkeypatch):
    monkeypatch.setattr(warp, "_WIREPROXY_PROC", _fake_proc(alive=False))
    monkeypatch.setattr(warp, "_socks_connectable", lambda timeout=2.0: True)
    assert warp.proxy_available() is False


def test_proxy_available_external_url_without_process(monkeypatch):
    monkeypatch.setenv("WARP_PROXY_URL", "socks5://127.0.0.1:1080")
    monkeypatch.setattr(warp, "_socks_connectable", lambda timeout=2.0: True)
    assert warp.proxy_available() is True
    monkeypatch.setattr(warp, "_socks_connectable", lambda timeout=2.0: False)
    assert warp.proxy_available() is False


# --- egress_status -----------------------------------------------------------

def test_egress_status_parses_trace(monkeypatch):
    def fake_run(argv, **kwargs):
        assert "--socks5-hostname" in argv
        return SimpleNamespace(returncode=0, stdout="fl=1\nwarp=on\nip=203.0.113.7\n")
    monkeypatch.setattr(warp.subprocess, "run", fake_run)
    assert warp.egress_status() == {"warp": "on", "ip": "203.0.113.7"}


def test_egress_status_curl_missing(monkeypatch):
    monkeypatch.setattr(warp.subprocess, "run",
                        lambda *a, **k: (_ for _ in ()).throw(FileNotFoundError("curl")))
    assert warp.egress_status() == {}


def test_egress_status_disabled(monkeypatch):
    monkeypatch.setenv("WARP_ENABLED", "0")
    assert warp.egress_status() == {}


# --- state + wireproxy conf ---------------------------------------------------

def test_state_roundtrip_and_corrupt(tmp_path):
    warp.warp_dir().mkdir(parents=True)
    warp._save_state({"enrolments": 2, "reenroll_generation": "g7"})
    assert warp._load_state() == {"enrolments": 2, "reenroll_generation": "g7"}
    (tmp_path / "warp" / warp.STATE_FILE).write_text("{not json")
    assert warp._load_state() == {"enrolments": 0, "reenroll_generation": ""}


def test_wireproxy_conf_imports_profile_without_keys(tmp_path):
    warp.warp_dir().mkdir(parents=True)
    (tmp_path / "warp" / warp.WGCF_PROFILE_FILE).write_text(
        "[Interface]\nPrivateKey = SECRETKEYXYZ\n")
    conf = warp._build_wireproxy_conf()
    text = conf.read_text(encoding="utf-8")
    assert f"WGConfig = {tmp_path / 'warp' / warp.WGCF_PROFILE_FILE}" in text
    assert "[Socks5]" in text
    assert "BindAddress = 127.0.0.1:1080" in text
    assert "SECRETKEYXYZ" not in text
    assert "0.0.0.0" not in text  # loopback only, never published


# --- ensure_warp ---------------------------------------------------------------

def test_ensure_warp_disabled_is_noop(monkeypatch):
    monkeypatch.setenv("WARP_ENABLED", "0")
    monkeypatch.setattr(warp, "_run_wgcf",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not run")))
    assert warp.ensure_warp() is False


def test_ensure_warp_enrols_when_no_profile(monkeypatch, tmp_path):
    _fake_wgcf_success(monkeypatch, tmp_path)
    monkeypatch.setattr(warp, "_start_wireproxy", lambda conf: _fake_proc(alive=True))
    monkeypatch.setattr(warp, "_wait_for_tunnel", lambda timeout=20: True)
    assert warp.ensure_warp() is True
    assert (tmp_path / "warp" / warp.WGCF_PROFILE_FILE).is_file()
    assert warp._load_state()["enrolments"] == 1
    assert warp._WIREPROXY_PROC is not None


def test_ensure_warp_cap_blocks_fourth_enrolment(monkeypatch, tmp_path):
    warp.warp_dir().mkdir(parents=True)
    warp._save_state({"enrolments": 3, "reenroll_generation": ""})
    monkeypatch.setattr(warp, "_run_wgcf",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not enrol")))
    assert warp.ensure_warp() is False
    assert not (tmp_path / "warp" / warp.WGCF_PROFILE_FILE).exists()


def test_ensure_warp_wgcf_missing_stays_direct(monkeypatch):
    monkeypatch.setattr(warp, "_run_wgcf",
                        lambda *a, **k: (_ for _ in ()).throw(FileNotFoundError("wgcf")))
    assert warp.ensure_warp() is False


def test_ensure_warp_tunnel_failure_stops_wireproxy(monkeypatch, tmp_path):
    _fake_wgcf_success(monkeypatch, tmp_path)
    proc = _fake_proc(alive=True)
    monkeypatch.setattr(warp, "_start_wireproxy", lambda conf: proc)
    monkeypatch.setattr(warp, "_wait_for_tunnel", lambda timeout=20: False)
    assert warp.ensure_warp() is False
    assert proc.calls["terminate"] == 1
    assert warp._WIREPROXY_PROC is None


def test_ensure_warp_reenrol_on_new_generation(monkeypatch, tmp_path):
    """WARP_REENROLL=new deletes the old profile and registers once;
    the same value on the next boot does nothing."""
    warp.warp_dir().mkdir(parents=True)
    (tmp_path / "warp" / warp.WGCF_PROFILE_FILE).write_text("old profile")
    warp._save_state({"enrolments": 1, "reenroll_generation": "g1"})
    calls = {"register": 0}

    def counting_run(args, **kwargs):
        if args and args[0] == "register":
            calls["register"] += 1
        if args and args[0] == "generate":
            (tmp_path / "warp" / warp.WGCF_PROFILE_FILE).write_text(
                "[Interface]\nPrivateKey = NEWKEY\n")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(warp, "_run_wgcf", counting_run)
    monkeypatch.setattr(warp, "_start_wireproxy", lambda conf: _fake_proc(alive=True))
    monkeypatch.setattr(warp, "_wait_for_tunnel", lambda timeout=20: True)
    monkeypatch.setenv("WARP_REENROLL", "g2")
    assert warp.ensure_warp() is True
    assert warp._load_state() == {"enrolments": 2, "reenroll_generation": "g2"}
    assert calls["register"] == 1
    assert (tmp_path / "warp" / warp.WGCF_PROFILE_FILE).read_text().startswith("[Interface]")
    # Same generation again: no second registration.
    calls["register"] = 0
    monkeypatch.setattr(warp, "_WIREPROXY_PROC", None)
    assert warp.ensure_warp() is True
    assert calls["register"] == 0
    assert warp._load_state()["enrolments"] == 2


def test_ensure_warp_reenrol_capped_keeps_profile(monkeypatch, tmp_path):
    warp.warp_dir().mkdir(parents=True)
    (tmp_path / "warp" / warp.WGCF_PROFILE_FILE).write_text("old profile")
    warp._save_state({"enrolments": 3, "reenroll_generation": "g1"})
    monkeypatch.setenv("WARP_REENROLL", "g2")
    monkeypatch.setattr(warp, "_run_wgcf",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not enrol")))
    monkeypatch.setattr(warp, "_start_wireproxy", lambda conf: _fake_proc(alive=True))
    monkeypatch.setattr(warp, "_wait_for_tunnel", lambda timeout=20: True)
    assert warp.ensure_warp() is True
    assert (tmp_path / "warp" / warp.WGCF_PROFILE_FILE).read_text() == "old profile"
    assert warp._load_state()["reenroll_generation"] == "g2"


def test_stop_warp_terminates_and_never_raises(monkeypatch):
    proc = _fake_proc(alive=True)
    monkeypatch.setattr(warp, "_WIREPROXY_PROC", proc)
    warp.stop_warp()
    assert proc.calls["terminate"] == 1
    assert warp._WIREPROXY_PROC is None
    warp.stop_warp()  # no process: no-op, no raise


def test_wait_for_tunnel_dead_process_returns_false(monkeypatch):
    monkeypatch.setattr(warp, "_WIREPROXY_PROC", _fake_proc(alive=False))
    assert warp._wait_for_tunnel(timeout=1) is False


# --- youtube download wiring ---------------------------------------------------

def _proxy_up(monkeypatch):
    monkeypatch.setattr(yt._warp, "proxy_available", lambda: True)
    monkeypatch.setattr(yt._warp, "proxy_url", lambda: "socks5://127.0.0.1:1080")


def _proxy_down(monkeypatch):
    monkeypatch.setattr(yt._warp, "proxy_available", lambda: False)
    monkeypatch.setattr(yt._warp, "proxy_url", lambda: "socks5://127.0.0.1:1080")


def test_download_uses_proxy_when_up(monkeypatch, tmp_path):
    """Every download attempt carries --proxy + --force-ipv4 when the
    tunnel is up."""
    _proxy_up(monkeypatch)
    calls = []

    def fake_run(argv, **kwargs):
        calls.append(argv)
        raise RuntimeError("yt-dlp failed: ERROR: [youtube] x: Sign in to confirm you're not a bot.")

    monkeypatch.setattr(yt, "_run_yt_dlp", fake_run)
    with pytest.raises(RuntimeError):
        yt.download("https://www.youtube.com/watch?v=dQw4w9WgXcQ", False,
                    out_dir=str(tmp_path / "req"))
    assert len(calls) == 7
    for c in calls:
        assert "--proxy" in c
        assert c[c.index("--proxy") + 1] == "socks5://127.0.0.1:1080"
        assert "--force-ipv4" in c


def test_download_direct_when_proxy_down(monkeypatch, tmp_path):
    """Proxy down: no --proxy anywhere, but --force-ipv4 stays (it
    helps the direct path too)."""
    _proxy_down(monkeypatch)
    calls = []

    def fake_run(argv, **kwargs):
        calls.append(argv)
        raise RuntimeError("yt-dlp failed: ERROR: [youtube] x: Sign in to confirm you're not a bot.")

    monkeypatch.setattr(yt, "_run_yt_dlp", fake_run)
    with pytest.raises(RuntimeError):
        yt.download("https://www.youtube.com/watch?v=dQw4w9WgXcQ", False,
                    out_dir=str(tmp_path / "req"))
    assert len(calls) == 7
    assert all("--proxy" not in c for c in calls)
    assert all("--force-ipv4" in c for c in calls)


def test_proxy_breaker_trips_on_proxy_error(monkeypatch, tmp_path):
    """A proxied attempt failing with a proxy error trips the breaker:
    the remaining attempts in the SAME chain go direct."""
    _proxy_up(monkeypatch)
    calls = []

    def fake_run(argv, **kwargs):
        calls.append(argv)
        raise RuntimeError("yt-dlp failed: ERROR: Unable to connect to proxy (SOCKS5)")

    monkeypatch.setattr(yt, "_run_yt_dlp", fake_run)
    with pytest.raises(RuntimeError):
        yt.download("https://www.youtube.com/watch?v=dQw4w9WgXcQ", False,
                    out_dir=str(tmp_path / "req"))
    assert len(calls) == 7
    assert "--proxy" in calls[0]
    assert all("--proxy" not in c for c in calls[1:])


def test_proxy_breaker_not_tripped_by_youtube_botcheck(monkeypatch, tmp_path):
    """A YouTube bot-check THROUGH the proxy is not a proxy failure:
    the whole chain keeps using WARP."""
    _proxy_up(monkeypatch)
    calls = []

    def fake_run(argv, **kwargs):
        calls.append(argv)
        raise RuntimeError("yt-dlp failed: ERROR: [youtube] x: Sign in to confirm you're not a bot.")

    monkeypatch.setattr(yt, "_run_yt_dlp", fake_run)
    with pytest.raises(RuntimeError):
        yt.download("https://www.youtube.com/watch?v=dQw4w9WgXcQ", False,
                    out_dir=str(tmp_path / "req"))
    assert len(calls) == 7
    assert all("--proxy" in c for c in calls)


def test_resolve_and_search_stay_direct(monkeypatch):
    """Only the download path gets the proxy — resolve_query (player
    metadata) and search_query (ytsearch) stay direct even when the
    tunnel is up."""
    _proxy_up(monkeypatch)
    import json as _json
    calls = []
    canned = _json.dumps({"id": "abc123", "title": "t", "duration": 10})

    def fake_run(argv, **kwargs):
        calls.append(argv)
        return SimpleNamespace(stdout=canned, stderr="", returncode=0)

    monkeypatch.setattr(yt, "_run_yt_dlp", fake_run)
    yt.resolve_query("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
    assert calls and all("--proxy" not in c for c in calls)
    calls.clear()
    yt.search_query("مروان موسي الخلاصه")
    assert calls and all("--proxy" not in c for c in calls)


def test_proxy_url_never_logged(monkeypatch, tmp_path, caplog):
    """The proxy URL (and anything in it) must not appear in logs —
    same discipline as the cookie content."""
    monkeypatch.setenv("WARP_PROXY_URL", "socks5://127.0.0.1:1080")
    _proxy_up(monkeypatch)
    monkeypatch.setattr(yt._warp, "proxy_url", lambda: "socks5://127.0.0.1:1080")
    with caplog.at_level(logging.INFO, logger="tools.youtube"):
        monkeypatch.setattr(yt, "_run_yt_dlp",
                            lambda argv, **k: (_ for _ in ()).throw(
                                RuntimeError("yt-dlp failed: ERROR: boom")))
        with pytest.raises(RuntimeError):
            yt.download("https://www.youtube.com/watch?v=dQw4w9WgXcQ", False,
                        out_dir=str(tmp_path / "req"))
    assert "127.0.0.1:1080" not in caplog.text


# --- status file (v1.11) -------------------------------------------------------
# data/warp/status.json is written on every state change so /healthz can
# tell "tunnel never came up" (down) from "tunnel up, YouTube flags the
# WARP IP" (on) without log access.

def _status(tmp_path):
    return json.loads((tmp_path / "warp" / warp.STATUS_FILE).read_text())


def test_status_file_on_when_tunnel_up(monkeypatch, tmp_path):
    _fake_wgcf_success(monkeypatch, tmp_path)
    monkeypatch.setattr(warp, "_start_wireproxy", lambda conf: _fake_proc(alive=True))
    monkeypatch.setattr(warp, "_wait_for_tunnel", lambda timeout=20: True)
    monkeypatch.setattr(warp, "egress_status",
                        lambda: {"warp": "on", "ip": "203.0.113.7"})
    assert warp.ensure_warp() is True
    status = _status(tmp_path)
    assert status["warp"] == "on"
    assert status["ip"] == "203.0.113.7"
    assert status["enrolments"] == 1
    assert isinstance(status["updated"], int) and status["updated"] > 0
    assert warp.read_status() == status


def test_status_file_down_when_tunnel_fails(monkeypatch, tmp_path):
    _fake_wgcf_success(monkeypatch, tmp_path)
    proc = _fake_proc(alive=True)
    monkeypatch.setattr(warp, "_start_wireproxy", lambda conf: proc)
    monkeypatch.setattr(warp, "_wait_for_tunnel", lambda timeout=20: False)
    assert warp.ensure_warp() is False
    status = _status(tmp_path)
    assert status["warp"] == "down"
    assert status["ip"] is None
    assert status["enrolments"] == 1  # enrolment happened; the tunnel did not


def test_status_file_off_when_disabled(monkeypatch, tmp_path):
    monkeypatch.setenv("WARP_ENABLED", "0")
    assert warp.ensure_warp() is False
    status = _status(tmp_path)
    assert status["warp"] == "off"
    assert status["ip"] is None
    assert status["enrolments"] == 0


def test_status_file_down_when_enrolment_fails(monkeypatch, tmp_path):
    monkeypatch.setattr(warp, "_run_wgcf",
                        lambda *a, **k: (_ for _ in ()).throw(FileNotFoundError("wgcf")))
    assert warp.ensure_warp() is False
    assert _status(tmp_path)["warp"] == "down"


def test_read_status_unknown_when_no_file():
    assert warp.read_status() == {
        "warp": "unknown", "ip": None, "enrolments": 0, "updated": None}


def test_read_status_corrupt_file_returns_unknown(tmp_path):
    warp.warp_dir().mkdir(parents=True)
    (tmp_path / "warp" / warp.STATUS_FILE).write_text("not json{")
    assert warp.read_status()["warp"] == "unknown"


def test_stop_warp_writes_down(monkeypatch, tmp_path):
    _fake_wgcf_success(monkeypatch, tmp_path)
    monkeypatch.setattr(warp, "_start_wireproxy", lambda conf: _fake_proc(alive=True))
    monkeypatch.setattr(warp, "_wait_for_tunnel", lambda timeout=20: True)
    monkeypatch.setattr(warp, "egress_status",
                        lambda: {"warp": "on", "ip": "203.0.113.7"})
    assert warp.ensure_warp() is True
    assert warp.read_status()["warp"] == "on"
    warp.stop_warp()
    status = warp.read_status()
    assert status["warp"] == "down"
    assert status["ip"] is None  # the down write carries no egress IP
