"""SSRF validation tests for tools/search.py (v0.5 Workstream A).

Uses a local HTTP server for redirect / body-cap / fetch_many tests.
validate_url is monkeypatched to an identity (or selective) fake only
where the test needs to reach the local server — the real validator
rejects 127.0.0.1 outright, which is itself asserted below.
"""
import asyncio
import http.server
import threading

import pytest

from tools.search import (
    MAX_BODY_BYTES,
    _fetch,
    fetch_many,
    validate_url,
)

REJECT_URLS = [
    "http://169.254.169.254/",
    "http://127.0.0.1/",
    "http://10.0.0.5/",
    "http://192.168.1.1/",
    "http://[::1]/",
    "file:///etc/passwd",
    "ftp://x/",
    "http://172.16.0.9/admin",
    "https://example.com@evil.com/",
    "gopher://example.com/",
    "--exec",
]

ACCEPT_URLS = [
    "https://www.youtube.com/watch?v=x",
    "https://example.com/page",
]


@pytest.mark.parametrize("url", REJECT_URLS)
def test_validate_url_rejects(url):
    with pytest.raises(ValueError):
        validate_url(url)


@pytest.mark.parametrize("url", ACCEPT_URLS)
def test_validate_url_accepts(url):
    assert validate_url(url) == url


class _Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        if self.path == "/redirect":
            self.send_response(302)
            self.send_header("Location", f"http://127.0.0.1:{self.server.server_port}/target")
            self.end_headers()
        elif self.path == "/target":
            body = b"secret-target"
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/big":
            body = b"x" * (MAX_BODY_BYTES + 100)
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/small":
            body = b"hello"
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/page":
            body = (
                "<html><head><title>Test Page</title></head><body><p>"
                + "word " * 100
                + "</p></body></html>"
            ).encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/short":
            body = b"<html><head><title>S</title></head><body><p>tiny</p></body></html>"
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.end_headers()


@pytest.fixture(scope="module")
def server():
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield srv
    srv.shutdown()
    srv.server_close()


def _base(server):
    return f"http://localhost:{server.server_port}"


def test_fetch_direct_private_ip_rejected(server):
    # Real validator: even the local server's own IP is blocked.
    with pytest.raises(ValueError):
        _fetch(f"http://127.0.0.1:{server.server_port}/small")


def test_fetch_redirect_to_private_ip_rejected(server, monkeypatch):
    def fake_validate(url):
        if "127.0.0.1" in url:
            raise ValueError("blocked IP")
        return url

    monkeypatch.setattr("tools.search.validate_url", fake_validate)
    with pytest.raises(ValueError):
        _fetch(f"{_base(server)}/redirect")


def test_fetch_body_cap(server, monkeypatch):
    monkeypatch.setattr("tools.search.validate_url", lambda u: u)
    with pytest.raises(ValueError, match="1 MB"):
        _fetch(f"{_base(server)}/big")
    status, _ct, text = _fetch(f"{_base(server)}/small")
    assert status == 200
    assert text == "hello"


def test_fetch_many_skips_youtube_and_short_pages(server, monkeypatch):
    monkeypatch.setattr("tools.search.validate_url", lambda u: u)
    results = asyncio.run(fetch_many([
        f"{_base(server)}/page",
        f"{_base(server)}/short",
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
    ]))
    by_url = {r["url"]: r for r in results}
    assert len(results) == 2
    assert by_url[f"{_base(server)}/page"]["skipped"] is False
    assert len(by_url[f"{_base(server)}/page"]["text"]) >= 200
    assert by_url[f"{_base(server)}/page"]["title"] == "Test Page"
    yt = by_url["https://www.youtube.com/watch?v=dQw4w9WgXcQ"]
    assert yt["skipped"] is True and yt["text"] == ""
    assert f"{_base(server)}/short" not in by_url
