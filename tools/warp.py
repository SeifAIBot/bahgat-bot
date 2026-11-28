"""Cloudflare WARP egress for YouTube downloads (v1.10).

Why: YouTube bot-checks Cloady's datacenter IP on the player API — every
client, token and cookie fails there, while the same chain works from any
other IP (diagnosis 2026-11-27; expert research in
~/workspace/research_notes/youtube-blocked-ip-expert-methods-20261127/report.md).
The only free, no-account fix with a controlled measurement is changing
the egress IP via Cloudflare WARP (0/12 downloads direct -> 11/12 via
WARP, 2026-09-03). WARP is a reputation lottery YouTube can re-flag;
re-registration is the cheap reset.

How (userspace, no privileges — fits Cloady's single container):
  wgcf registers a free WARP identity (no account/email/card) and
  generates a WireGuard profile; wireproxy runs WireGuard in userspace
  and exposes a SOCKS5 proxy on 127.0.0.1:1080. Only the yt-dlp DOWNLOAD
  path goes through it (tools/youtube.py); search, Telegram polling and
  LLM calls stay direct.

Persistence: the wgcf profile + account live under data/warp/ (the
/app/data volume on Cloady), so enrolment survives redeploys. Enrolments
are capped at MAX_ENROLMENTS (3) — a fresh enrolment is a dice roll and
must not loop forever. Re-enrolment is operator-triggered via the
WARP_REENROLL env var: set it to a new value and the next boot deletes
the profile and re-registers once (generation is stored in warp-state.json).

Kill switch: WARP_ENABLED=false (or 0/no/off) disables the whole
subsystem — downloads go direct, exactly as before. Any failure anywhere
in this module degrades to direct downloads; NOTHING here may crash the
bot. ensure_warp() is started from main.py in a daemon thread so a slow
tunnel never delays polling.

Gate check (the research's step 1): after wireproxy is up, a curl through
the proxy to cloudflare.com/cdn-cgi/trace must return warp=on, and the
egress IP is logged. If outbound UDP is blocked on the host, the tunnel
never comes up and downloads stay direct — that is the expected failure
mode, not a crash.

Status file (v1.11): every state change writes data/warp/status.json —
{"warp": "on"|"off"|"down", "ip": <egress>, "enrolments": n,
"updated": <unix ts>}. The egress IP is a datacenter/WARP address, not
a secret (see egress_status). /healthz exposes this file, so the two
live failure modes are distinguishable from outside without log access
(the Cloady free tier cannot show data/bot.log): "down" = the tunnel
never came up (UDP blocked); "on" + an IP = the tunnel is up and the
download failure is something else (e.g. YouTube flagging the WARP IP).
"off" = WARP disabled via the kill switch. No file yet = "unknown"
(the warp thread has not run since boot).
"""
import json
import logging
import os
import socket
import subprocess
import time
from pathlib import Path

from core.config import data_dir

logger = logging.getLogger(__name__)

WARP_DIR_NAME = "warp"
WGCF_ACCOUNT_FILE = "wgcf-account.toml"
WGCF_PROFILE_FILE = "wgcf-profile.conf"
WIREPROXY_CONF_FILE = "wireproxy.conf"
WIREPROXY_LOG_FILE = "wireproxy.log"
STATE_FILE = "warp-state.json"
STATUS_FILE = "status.json"

SOCKS_HOST = "127.0.0.1"
SOCKS_PORT = 1080
INFO_HOST = "127.0.0.1"
INFO_PORT = 9080

DEFAULT_PROXY_URL = f"socks5://{SOCKS_HOST}:{SOCKS_PORT}"
TRACE_URL = "https://cloudflare.com/cdn-cgi/trace"

# Cap on total WARP enrolments (first + re-enrolments). A fresh enrolment
# is a dice roll; beyond this, stop burning registrations and stay direct.
MAX_ENROLMENTS = 3

# wireproxy readiness: how long to wait for warp=on after starting it.
_TUNNEL_WAIT_SECONDS = 20
_TRACE_TIMEOUT_SECONDS = 5
# wireproxy log: truncate on start past this size so the volume can
# never fill up with tunnel logs.
_WIREPROXY_LOG_MAX_BYTES = 256 * 1024

WGCF_BIN = "wgcf"
WIREPROXY_BIN = "wireproxy"

# The running wireproxy process (started by ensure_warp, stopped by
# stop_warp). None when WARP is disabled, failed, or not started yet.
_WIREPROXY_PROC = None
# Open handle to data/warp/wireproxy.log, owned by the Popen above;
# closed when the process is stopped (otherwise it leaks an fd per start).
_WIREPROXY_LOG_HANDLE = None

_FALSE_VALUES = {"0", "false", "no", "off"}
_TRUE_VALUES = {"1", "true", "yes", "on"}


def warp_enabled() -> bool:
    """Kill switch. Unset/empty = ON (default once verified); explicit
    false values turn the whole subsystem off. An unrecognised value
    warns and stays ON — the default the task brief sets."""
    raw = (os.environ.get("WARP_ENABLED") or "").strip().lower()
    if not raw:
        return True
    if raw in _FALSE_VALUES:
        return False
    if raw in _TRUE_VALUES:
        return True
    logger.warning("WARP_ENABLED=%r is not a recognised value; treating as enabled", raw)
    return True


def warp_dir() -> Path:
    """Where the WARP profile/state live: data/warp/ under the bot's
    data dir (the persistent volume on Cloady). Read at call time so
    BAHGAT_DATA_DIR changes and test overrides always apply."""
    return data_dir() / WARP_DIR_NAME


def proxy_url() -> str | None:
    """The SOCKS5 URL yt-dlp should use, or None when WARP is disabled.
    WARP_PROXY_URL overrides the default (operator-provided external
    proxy, e.g. for tests) — the URL is never logged."""
    if not warp_enabled():
        return None
    override = (os.environ.get("WARP_PROXY_URL") or "").strip()
    return override or DEFAULT_PROXY_URL


def _socks_connectable(timeout: float = 2.0) -> bool:
    """True when something answers a TCP connect on the SOCKS port.
    Proves wireproxy is listening, NOT that the tunnel is up — the
    trace check (egress_status) is the real gate."""
    try:
        with socket.create_connection((SOCKS_HOST, SOCKS_PORT), timeout=timeout):
            return True
    except OSError:
        return False


def proxy_available() -> bool:
    """True when a download may go through the proxy: WARP enabled, our
    wireproxy process alive (or an external proxy URL configured), and
    the SOCKS port answering. Checked per download attempt (loopback
    connect is sub-ms); the tunnel itself is validated at startup by
    the warp=on trace check and by the proxy-error circuit breaker in
    tools/youtube.py."""
    if not warp_enabled():
        return False
    proc = _WIREPROXY_PROC
    if proc is not None and proc.poll() is not None:
        return False
    if proc is None and not (os.environ.get("WARP_PROXY_URL") or "").strip():
        return False
    return _socks_connectable()


def egress_status(timeout: int = _TRACE_TIMEOUT_SECONDS) -> dict:
    """Ask Cloudflare (through the proxy) who we egress as.

    Returns {"warp": "on"/"off"/None, "ip": str|None}. {} when curl is
    missing or the check fails — the caller logs that, never crashes.
    The egress IP is diagnostic (the research says to log it on every
    download); it is a datacenter/WARP address, not a secret.
    """
    url = proxy_url()
    if url is None:
        return {}
    try:
        res = subprocess.run(
            ["curl", "-s", "--max-time", str(timeout),
             "--socks5-hostname", url, TRACE_URL],
            capture_output=True, text=True, timeout=timeout + 5,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as e:
        logger.debug("warp trace check unavailable (%s)", e)
        return {}
    if res.returncode != 0:
        logger.debug("warp trace check failed (curl exit %s)", res.returncode)
        return {}
    out = {}
    for line in (res.stdout or "").splitlines():
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        if key.strip() in ("warp", "ip"):
            out[key.strip()] = value.strip()
    return out


# --- state ---------------------------------------------------------------

def _load_state() -> dict:
    """{"enrolments": int, "reenroll_generation": str}. Corrupt/missing
    file -> defaults (logged, never raised)."""
    path = warp_dir() / STATE_FILE
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("state is not an object")
        return {
            "enrolments": int(data.get("enrolments") or 0),
            "reenroll_generation": str(data.get("reenroll_generation") or ""),
        }
    except (OSError, ValueError, TypeError) as e:
        if path.exists():
            logger.warning("warp state unreadable (%s); starting fresh", e)
        return {"enrolments": 0, "reenroll_generation": ""}


def _save_state(state: dict) -> None:
    path = warp_dir() / STATE_FILE
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(state, f)
        except Exception:
            try:
                os.close(fd)
            except OSError:
                pass
            raise
        os.chmod(path, 0o600)
    except OSError as e:
        logger.warning("could not save warp state (%s)", e)


# --- status file (v1.11) ---------------------------------------------------

def _write_status(warp: str, ip: str | None = None) -> None:
    """Write data/warp/status.json on every state change.

    warp is "on" (tunnel up, gate check passed), "off" (kill switch),
    or "down" (tunnel never came up / stopped). The enrolment count
    comes from the persisted state. Best-effort: a failed write is
    logged and never raises — status must not break the tunnel path.
    The egress IP is a datacenter/WARP address, not a secret.
    """
    path = warp_dir() / STATUS_FILE
    try:
        enrolments = _load_state().get("enrolments", 0)
        payload = {
            "warp": warp,
            "ip": ip,
            "enrolments": enrolments,
            "updated": int(time.time()),
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload), encoding="utf-8")
    except OSError as e:
        logger.warning("could not write warp status (%s)", e)


def read_status() -> dict:
    """The status file for /healthz, or the "unknown" default when no
    state change has been recorded yet (warp thread not run since boot)
    or the file is corrupt. Never raises."""
    default = {"warp": "unknown", "ip": None, "enrolments": 0, "updated": None}
    path = warp_dir() / STATUS_FILE
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or data.get("warp") not in (
                "on", "off", "down", "unknown"):
            raise ValueError("bad status payload")
        return {
            "warp": data.get("warp", "unknown"),
            "ip": data.get("ip"),
            "enrolments": int(data.get("enrolments") or 0),
            "updated": data.get("updated"),
        }
    except (OSError, ValueError, TypeError):
        return default


def _chmod_private(path: Path) -> None:
    """Best-effort 0600 on files holding the WARP private key."""
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


# --- wgcf -----------------------------------------------------------------

def _run_wgcf(args: list[str], timeout: int) -> subprocess.CompletedProcess:
    """Run wgcf in the warp dir (it writes wgcf-account.toml /
    wgcf-profile.conf to its CWD). Raises on missing binary / non-zero
    exit / timeout — callers convert that to 'stay direct'."""
    return subprocess.run(
        [WGCF_BIN, *args], cwd=str(warp_dir()), timeout=timeout,
        capture_output=True, text=True,
    )


def _enrol() -> bool:
    """Register a free WARP identity and generate the WireGuard profile.
    --accept-tos: non-interactive (no prompt on first run). Returns True
    only when wgcf-profile.conf exists afterwards."""
    try:
        reg = _run_wgcf(["register", "--accept-tos"], timeout=60)
        if reg.returncode != 0:
            logger.warning("warp enrolment: wgcf register failed (exit %s): %s",
                           reg.returncode, (reg.stderr or reg.stdout or "")[:300])
            return False
        gen = _run_wgcf(["generate", "-p", WGCF_PROFILE_FILE], timeout=30)
        if gen.returncode != 0:
            logger.warning("warp enrolment: wgcf generate failed (exit %s): %s",
                           gen.returncode, (gen.stderr or gen.stdout or "")[:300])
            return False
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as e:
        logger.warning("warp enrolment failed (%s)", e)
        return False
    profile = warp_dir() / WGCF_PROFILE_FILE
    if not profile.is_file():
        logger.warning("warp enrolment: wgcf-profile.conf missing after generate")
        return False
    _chmod_private(profile)
    _chmod_private(warp_dir() / WGCF_ACCOUNT_FILE)
    logger.info("warp enrolment: profile generated")
    return True


# --- wireproxy ------------------------------------------------------------

def _build_wireproxy_conf() -> Path:
    """Write wireproxy.conf importing the wgcf profile and exposing the
    SOCKS5 listener on loopback only (never published). WGConfig import
    keeps the private key in the one wgcf file — no key material is
    copied into this config."""
    conf = warp_dir() / WIREPROXY_CONF_FILE
    profile = warp_dir() / WGCF_PROFILE_FILE
    text = (
        "# Generated by tools/warp.py (v1.10) — do not edit by hand.\n"
        f"WGConfig = {profile}\n"
        "\n"
        "# SOCKS5 on loopback ONLY: yt-dlp talks to it, nothing else can.\n"
        "[Socks5]\n"
        f"BindAddress = {SOCKS_HOST}:{SOCKS_PORT}\n"
    )
    conf.write_text(text, encoding="utf-8")
    _chmod_private(conf)
    return conf


def _start_wireproxy(conf: Path):
    """Start wireproxy in the background. Logs to data/warp/wireproxy.log
    (truncated on start past 256 KB). Returns the Popen object, or None
    when the binary is missing / will not start."""
    global _WIREPROXY_LOG_HANDLE
    log_path = warp_dir() / WIREPROXY_LOG_FILE
    try:
        if log_path.exists() and log_path.stat().st_size > _WIREPROXY_LOG_MAX_BYTES:
            log_path.unlink()
        _WIREPROXY_LOG_HANDLE = open(log_path, "ab")  # noqa: SIM115 — closed in _stop_wireproxy_locked
        log_file = _WIREPROXY_LOG_HANDLE
    except OSError as e:
        logger.warning("warp: cannot open wireproxy log (%s); using DEVNULL", e)
        log_file = subprocess.DEVNULL
    try:
        proc = subprocess.Popen(
            [WIREPROXY_BIN, "-c", str(conf), "-i", f"{INFO_HOST}:{INFO_PORT}"],
            cwd=str(warp_dir()), stdout=log_file, stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    except (FileNotFoundError, OSError) as e:
        logger.warning("warp: wireproxy would not start (%s)", e)
        return None
    return proc


def _wait_for_tunnel(timeout: int = _TUNNEL_WAIT_SECONDS) -> bool:
    """Poll until the trace check through the proxy returns warp=on.
    The SOCKS port answering is not enough — wireproxy binds it even
    with a dead tunnel. Returns False on timeout (caller kills the
    process and stays direct)."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        proc = _WIREPROXY_PROC
        if proc is not None and proc.poll() is not None:
            logger.warning("warp: wireproxy exited early (code %s)", proc.returncode)
            return False
        if not _socks_connectable(timeout=1.0):
            time.sleep(1)
            continue
        status = egress_status()
        if status.get("warp") == "on":
            logger.info("warp: tunnel up, egress ip=%s warp=on",
                        status.get("ip", "?"))
            return True
        time.sleep(1)
    logger.warning("warp: tunnel did not come up in %ss (no warp=on)", timeout)
    return False


# --- lifecycle --------------------------------------------------------------

def ensure_warp() -> bool:
    """Bring the WARP proxy up (idempotent-ish: a running wireproxy is
    left alone). Runs at boot in a daemon thread — never blocks polling
    and NEVER raises: any failure logs a warning and downloads go
    direct, exactly as before v1.10."""
    global _WIREPROXY_PROC
    try:
        return _ensure_warp_inner()
    except Exception as e:  # noqa: BLE001 — this is the last line of defence
        logger.warning("warp: unexpected failure (%s); downloads stay direct", e)
        return False


def _ensure_warp_inner() -> bool:
    global _WIREPROXY_PROC
    if not warp_enabled():
        logger.info("warp: disabled (WARP_ENABLED off); downloads go direct")
        _write_status("off")
        return False
    if _WIREPROXY_PROC is not None and _WIREPROXY_PROC.poll() is None:
        return True
    warp_dir().mkdir(parents=True, exist_ok=True)
    state = _load_state()
    profile = warp_dir() / WGCF_PROFILE_FILE

    # Operator-triggered re-enrolment: WARP_REENROLL set to a value we
    # have not acted on yet. Deletes the old identity and registers a
    # fresh one — the dice roll when the current egress is flagged.
    requested = (os.environ.get("WARP_REENROLL") or "").strip()
    reenrol_attempted = False
    if requested and requested != state.get("reenroll_generation"):
        reenrol_attempted = True
        if state["enrolments"] >= MAX_ENROLMENTS:
            logger.warning(
                "warp: re-enrolment cap reached (%d enrolments); "
                "ignoring WARP_REENROLL=%r — downloads stay on the "
                "current profile (or direct if none)", MAX_ENROLMENTS, requested)
            state["reenroll_generation"] = requested
            _save_state(state)
        else:
            _stop_wireproxy_locked()
            for name in (WGCF_ACCOUNT_FILE, WGCF_PROFILE_FILE, WIREPROXY_CONF_FILE):
                try:
                    (warp_dir() / name).unlink(missing_ok=True)
                except OSError:
                    pass
            logger.info("warp: re-enrolling (generation %r)", requested)
            if _enrol():
                state["enrolments"] += 1
            state["reenroll_generation"] = requested
            _save_state(state)
            profile = warp_dir() / WGCF_PROFILE_FILE

    if not profile.is_file():
        if reenrol_attempted:
            # The re-enrolment above already tried once this boot; do
            # not burn a second registration on the same failure.
            _write_status("down")
            return False
        if state["enrolments"] >= MAX_ENROLMENTS:
            logger.warning(
                "warp: no profile and enrolment cap reached (%d); "
                "downloads stay direct", MAX_ENROLMENTS)
            _write_status("down")
            return False
        logger.info("warp: no profile yet, enrolling (attempt %d/%d)",
                    state["enrolments"] + 1, MAX_ENROLMENTS)
        if not _enrol():
            _write_status("down")
            return False
        state["enrolments"] += 1
        _save_state(state)

    conf = _build_wireproxy_conf()
    proc = _start_wireproxy(conf)
    if proc is None:
        _write_status("down")
        return False
    _WIREPROXY_PROC = proc
    if _wait_for_tunnel():
        # Gate passed: re-read the egress IP for the status file (the
        # trace check inside _wait_for_tunnel already proved warp=on).
        _write_status("on", ip=egress_status().get("ip"))
        return True
    _stop_wireproxy_locked()
    return False


def _stop_wireproxy_locked() -> None:
    global _WIREPROXY_PROC, _WIREPROXY_LOG_HANDLE
    proc = _WIREPROXY_PROC
    _WIREPROXY_PROC = None
    if proc is None:
        return
    # v1.11: the tunnel is stopping — record it, so /healthz never
    # reports a stale "on" after the proxy is gone.
    _write_status("down")
    try:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)
    except (OSError, subprocess.TimeoutExpired) as e:
        logger.warning("warp: error stopping wireproxy (%s)", e)
    finally:
        handle, _WIREPROXY_LOG_HANDLE = _WIREPROXY_LOG_HANDLE, None
        if handle is not None:
            try:
                handle.close()
            except OSError:
                pass


def stop_warp() -> None:
    """Stop wireproxy (called from main.py's shutdown path). Never raises."""
    try:
        _stop_wireproxy_locked()
    except Exception as e:  # noqa: BLE001 — shutdown path must not raise
        logger.warning("warp: error stopping wireproxy (%s)", e)
