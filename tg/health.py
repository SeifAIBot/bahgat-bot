"""Tiny HTTP health endpoint for PaaS health checks (e.g. Northflank).

The bot is polling-only, so without this there is no HTTP port for a host
to probe. Stdlib only — no new dependency. Runs in a daemon thread next
to the polling loop and shuts down with the app (see main.py).

Liveness signal is the same heartbeat file the polling loop already
writes (data/heartbeat.json, refreshed every 60s by tg/app.py):
  GET /healthz (or /health) -> 200 {"status":"ok", ...} when last_poll is
  < 300s old, otherwise 503 {"status":"unavailable", ...}.
Anything else -> 404. Only GET is served.

Binds 0.0.0.0:$PORT (env PORT, default 8080) — Northflank injects $PORT
and maps it to the service's public port.
"""
import json
import logging
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from core.config import data_dir

logger = logging.getLogger("bahgat.health")

HEALTH_PATHS = ("/healthz", "/health")
STALE_AFTER_SECONDS = 300
DEFAULT_PORT = 8080


def _heartbeat_age_seconds(heartbeat_path: Path) -> float | None:
    """Age of the polling heartbeat in seconds, or None if unknown."""
    try:
        payload = json.loads(heartbeat_path.read_text(encoding="utf-8"))
        last_poll = float(payload["last_poll"])
    except Exception:
        return None
    return time.time() - last_poll


def _check(heartbeat_path: Path) -> tuple[bool, float | None]:
    """(healthy, age_seconds). Healthy = heartbeat exists and is fresh."""
    age = _heartbeat_age_seconds(heartbeat_path)
    if age is None:
        return False, None
    return age < STALE_AFTER_SECONDS, age


def _make_handler(heartbeat_path: Path):
    class HealthHandler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *args):  # silence per-request access logs
            pass

        def _send_json(self, status: int, payload: dict) -> None:
            body = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):  # noqa: N802 - BaseHTTPRequestHandler naming
            if self.path in HEALTH_PATHS:
                healthy, age = _check(heartbeat_path)
                if healthy:
                    self._send_json(
                        200,
                        {"status": "ok", "last_poll_age_seconds": int(age)},
                    )
                else:
                    self._send_json(
                        503,
                        {
                            "status": "unavailable",
                            "last_poll_age_seconds": (
                                int(age) if age is not None else None
                            ),
                        },
                    )
            else:
                self._send_json(404, {"status": "not_found"})

    return HealthHandler


def resolve_port(port: int | None = None) -> int:
    """Explicit port wins, else $PORT, else 8080. Invalid value fails fast."""
    if port is not None:
        return port
    return int(os.environ.get("PORT", str(DEFAULT_PORT)))


def start_health_server(
    heartbeat_path: Path | None = None,
    port: int | None = None,
) -> ThreadingHTTPServer:
    """Start the health server in a daemon thread; returns the server.

    The caller owns shutdown via stop_health_server(). The daemon thread
    means a missed stop cannot keep the process alive — but main.py still
    stops it explicitly in a finally block for a clean SIGTERM shutdown.
    """
    path = heartbeat_path if heartbeat_path is not None else data_dir() / "heartbeat.json"
    server = ThreadingHTTPServer(
        ("0.0.0.0", resolve_port(port)), _make_handler(path)
    )
    thread = threading.Thread(
        target=server.serve_forever, name="health-server", daemon=True
    )
    thread.start()
    logger.info(
        "health server listening on 0.0.0.0:%d (heartbeat=%s)",
        server.server_address[1],
        path,
    )
    return server


def stop_health_server(server: ThreadingHTTPServer | None) -> None:
    """Block until the health server thread has stopped (max ~0.5s)."""
    if server is None:
        return
    try:
        server.shutdown()
        server.server_close()
    except Exception as e:
        logger.warning("health server shutdown failed: %s", e)
