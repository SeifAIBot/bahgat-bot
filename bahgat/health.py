"""Tiny /healthz HTTP endpoint for PaaS health checks. Stdlib only, daemon
thread, never crashes the bot."""
import json
import logging
import os
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

logger = logging.getLogger(__name__)


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802 (stdlib naming)
        if self.path in ("/healthz", "/"):
            body = json.dumps({"status": "ok"}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, *args):  # quiet
        pass


def start_health_server(port: int | None = None):
    """Start the health server; returns the HTTPServer (or None on failure)."""
    p = port or int(os.environ.get("PORT", "8080"))
    try:
        server = HTTPServer(("0.0.0.0", p), _Handler)
    except OSError as e:
        logger.warning("health server could not bind port %s: %s", p, e)
        return None
    threading.Thread(target=server.serve_forever, name="healthz", daemon=True).start()
    logger.info("health endpoint on :%s/healthz", p)
    return server


def stop_health_server(server) -> None:
    if server is not None:
        try:
            server.shutdown()
        except Exception:
            pass
