"""Web search — DuckDuckGo HTML (free, no key) + page fetch.

Kept from the old tools/search.py, trimmed: SSRF guard (https only,
private/loopback IPs refused, redirects re-validated, 1 MB body cap),
DDG redirect resolution, Lite fallback.
"""
import asyncio
import ipaddress
import socket
import urllib.error
import urllib.parse
import urllib.request
from urllib.parse import parse_qs, urljoin, urlparse

from bs4 import BeautifulSoup

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")
MAX_BODY_BYTES = 1_048_576
MAX_REDIRECTS = 3
DDG_HOSTS = {"duckduckgo.com", "html.duckduckgo.com", "lite.duckduckgo.com"}
SKIP_HOSTS = {
    "youtube.com", "www.youtube.com", "youtu.be", "music.youtube.com",
    "tiktok.com", "www.tiktok.com",
}

_BLOCKED_NETWORKS = [
    ipaddress.ip_network(n) for n in (
        "0.0.0.0/8", "10.0.0.0/8", "100.64.0.0/10", "127.0.0.0/8",
        "169.254.0.0/16", "172.16.0.0/12", "192.168.0.0/16", "224.0.0.0/4",
        "::/128", "::1/128", "fc00::/7", "fe80::/10", "ff00::/8",
    )
]


def _ip_is_blocked(ip_str: str) -> bool:
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return True
    if ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved or ip.is_unspecified:
        return True
    return any(ip in net for net in _BLOCKED_NETWORKS)


def validate_url(url: str) -> str:
    """Validate a URL for fetching; raises ValueError on anything fishy."""
    if not isinstance(url, str) or not url.strip():
        raise ValueError("empty URL")
    url = url.strip()
    if url.startswith("-"):
        raise ValueError("URL must not start with '-'")
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError(f"unsupported URL scheme: {parsed.scheme!r}")
    host = (parsed.hostname or "").lower()
    if not host:
        raise ValueError("URL has no hostname")
    if parsed.username or parsed.password:
        raise ValueError("URLs with embedded credentials are not allowed")
    if parsed.scheme == "http" and host not in DDG_HOSTS and not host.endswith(".duckduckgo.com"):
        raise ValueError("http is only allowed for duckduckgo.com hosts")
    try:
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
    except ValueError as e:
        raise ValueError(f"invalid port in URL: {e}") from e
    try:
        infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    except socket.gaierror as e:
        raise ValueError(f"cannot resolve host {host!r}: {e}") from e
    for info in infos or []:
        ip_str = info[4][0]
        if _ip_is_blocked(ip_str):
            raise ValueError(f"host {host!r} resolves to blocked IP {ip_str}")
    return url


class _ValidatedRedirectHandler(urllib.request.HTTPRedirectHandler):
    max_redirections = MAX_REDIRECTS

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        absolute = urljoin(req.full_url, newurl)
        validate_url(absolute)
        return super().redirect_request(req, fp, code, msg, headers, absolute)


def _resolve_ddg(href: str) -> str:
    if not href:
        return ""
    if href.startswith("//"):
        href = "https:" + href
    if "/l/?" in href or "uddg=" in href:
        q = parse_qs(urlparse(href).query)
        if "uddg" in q:
            return q["uddg"][0]
    return urljoin("https://duckduckgo.com", href)


def _fetch(url: str) -> tuple:
    url = validate_url(url)
    opener = urllib.request.build_opener(_ValidatedRedirectHandler())
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with opener.open(req, timeout=20) as r:
        ctype = r.headers.get("content-type", "")
        chunks = []
        total = 0
        while True:
            chunk = r.read(65536)
            if not chunk:
                break
            total += len(chunk)
            if total > MAX_BODY_BYTES:
                raise ValueError("response body exceeds ~1 MB cap")
            chunks.append(chunk)
        return r.status, ctype, b"".join(chunks).decode("utf-8", errors="replace")


def _clean_html(html: str) -> tuple:
    soup = BeautifulSoup(html, "html.parser")
    title = soup.title.get_text(" ", strip=True) if soup.title else ""
    for tag in soup(["script", "style", "nav", "header", "footer"]):
        tag.decompose()
    return title, soup.get_text(" ", strip=True)


def _fetch_one(url: str, limit_chars: int):
    host = (urlparse(url).hostname or "").lower()
    if host in SKIP_HOSTS or host.endswith(".youtube.com") or host.endswith(".tiktok.com"):
        return {"url": url, "title": "", "text": "", "skipped": True}
    try:
        status, ctype, html = _fetch(url)
    except Exception:
        return None
    if status != 200 or ("text/html" not in ctype and "text/plain" not in ctype):
        return None
    title, text = _clean_html(html)
    if len(text) < 200:
        return None
    return {"url": url, "title": title, "text": text[:limit_chars], "skipped": False}


async def fetch_many(urls, limit_chars: int = 800) -> list:
    urls = list(urls)[:3]
    results = await asyncio.gather(
        *(asyncio.to_thread(_fetch_one, u, limit_chars) for u in urls)
    )
    return [r for r in results if r is not None]


async def web_search(query: str, max_results: int = 5) -> list:
    """DuckDuckGo results: [{"title", "url"}, ...]. Empty list on failure."""
    for base, selector in (
        ("https://html.duckduckgo.com/html/", ".result__a"),
        ("https://lite.duckduckgo.com/lite/", "a.result-link"),
    ):
        url = base + "?" + urllib.parse.urlencode({"q": query})
        try:
            status, _ct, text = await asyncio.to_thread(_fetch, url)
        except Exception:
            continue
        if status != 200:
            continue
        soup = BeautifulSoup(text, "html.parser")
        out = []
        for a in soup.select(selector)[:max_results]:
            u = _resolve_ddg(a.get("href", ""))
            if not u:
                continue
            try:
                validate_url(u)
            except ValueError:
                continue
            out.append({"title": a.get_text(" ", strip=True), "url": u})
        if out:
            return out
    return []


def format_results_for_prompt(results: list, pages: list | None = None) -> str:
    """Numbered [1]..[n] source block for the LLM: titles, URLs, and the
    fetched page text when available."""
    parts = []
    texts = {p["url"]: p.get("text", "") for p in (pages or [])}
    for i, r in enumerate(results, 1):
        line = f"[{i}] {r.get('title', '')} — {r.get('url', '')}"
        body = texts.get(r.get("url"), "")
        if body:
            line += "\n" + body[:600]
        parts.append(line)
    return "\n\n".join(parts)
