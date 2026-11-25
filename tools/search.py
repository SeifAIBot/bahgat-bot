"""Web search — DuckDuckGo HTML (free, no key) + page fetch.
Uses urllib (not httpx): httpx mis-parses the NO_PROXY list in this VM
and fails SSL verification through the egress proxy, urllib works.
- Resolve DDG redirect hrefs (uddg param) to the real target URL.
- raise on HTTP error, content-type check, realistic User-Agent.
- Fallback to DuckDuckGo Lite if HTML returns 0 results.

SSRF hardening (v0.5, Workstream A):
- validate_url(): https only (http only for duckduckgo.com hosts, which the
  internal DDG calls use — they stay https anyway); hostname is resolved
  with socket.getaddrinfo and every resolved IP is checked against an
  explicit blocklist (10/8, 172.16/12, 192.168/16, 127/8, 169.254/16,
  ::1, fc00::/7, fe80::/10, multicast, reserved, unspecified).
  NOTE: ipaddress's is_private is deliberately NOT used: it is True for
  198.18.0.0/15, which this VM's egress proxy returns for public hosts.
- Redirects are followed only via _ValidatedRedirectHandler, which
  re-validates EVERY Location URL (max 3 redirects).
- Response body capped at ~1 MB (read in chunks, abort over cap).
- fetch_many(): fetch up to 3 pages in parallel, skipping YouTube/TikTok
  boilerplate hosts and pages with <200 chars of real text.
"""
import asyncio, ipaddress, socket, urllib.request, urllib.parse, urllib.error
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse, parse_qs

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
MAX_BODY_BYTES = 1_048_576  # ~1 MB
MAX_REDIRECTS = 3
DDG_HOSTS = {"duckduckgo.com", "html.duckduckgo.com", "lite.duckduckgo.com"}
# Hosts whose pages are boilerplate / not usable as fact sources.
SKIP_HOSTS = {
    "youtube.com", "www.youtube.com", "youtu.be", "music.youtube.com",
    "tiktok.com", "www.tiktok.com",
}

# Explicit SSRF blocklist. Deliberately NOT ipaddress.is_private (see note
# in the module docstring: 198.18/15 is "private" per ipaddress but is what
# this VM's egress proxy returns for ordinary public hosts).
_BLOCKED_NETWORKS = [
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("100.64.0.0/10"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("224.0.0.0/4"),      # IPv4 multicast
    ipaddress.ip_network("::/128"),          # unspecified
    ipaddress.ip_network("::1/128"),         # loopback
    ipaddress.ip_network("fc00::/7"),        # unique-local
    ipaddress.ip_network("fe80::/10"),       # link-local
    ipaddress.ip_network("ff00::/8"),        # IPv6 multicast
]


def _ip_is_blocked(ip_str: str) -> bool:
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return True  # unparseable address: fail closed
    if ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved or ip.is_unspecified:
        return True
    return any(ip in net for net in _BLOCKED_NETWORKS)


def validate_url(url: str) -> str:
    """Validate a URL for fetching. Returns the (stripped) URL.

    Raises ValueError for: empty/non-string input, non-http(s) schemes,
    http on any host other than duckduckgo.com, unresolvable hostnames,
    and hostnames resolving to a blocked (private/loopback/link-local/
    multicast/reserved) IP. DNS is resolved here; a second resolution
    happens inside urlopen (TOCTOU window is inherent to urllib — an
    egress proxy / domain allowlist is the long-term fix).
    """
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
    if not infos:
        raise ValueError(f"cannot resolve host {host!r}")
    for info in infos:
        ip_str = info[4][0]
        if _ip_is_blocked(ip_str):
            raise ValueError(f"host {host!r} resolves to blocked IP {ip_str}")
    return url


class _ValidatedRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Follows redirects only after re-validating each Location URL."""
    max_redirections = MAX_REDIRECTS

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        absolute = urljoin(req.full_url, newurl)
        validate_url(absolute)  # raises ValueError -> aborts the fetch
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


def _fetch(url: str) -> tuple[int, str, str]:
    """Synchronous fetch. Validates the URL, follows at most 3 redirects
    (each re-validated), 20s timeout, body capped at ~1 MB (ValueError
    if exceeded). Returns (status, content-type, decoded body)."""
    url = validate_url(url)
    opener = urllib.request.build_opener(_ValidatedRedirectHandler())
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with opener.open(req, timeout=20) as r:
        ctype = r.headers.get("content-type", "")
        chunks: list[bytes] = []
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


def _clean_html(html: str) -> tuple[str, str]:
    """Return (title, cleaned visible text) for an HTML document."""
    soup = BeautifulSoup(html, "html.parser")
    title = soup.title.get_text(" ", strip=True) if soup.title else ""
    for tag in soup(["script", "style", "nav", "header", "footer"]):
        tag.decompose()
    return title, soup.get_text(" ", strip=True)


def _fetch_one(url: str, limit_chars: int) -> dict | None:
    """Sync single-page fetch for fetch_many. Returns a result dict, or
    None when the page should be skipped (fetch failure or <200 chars
    of real text). YouTube/TikTok hosts return a skipped=True entry."""
    host = (urlparse(url).hostname or "").lower()
    if host in SKIP_HOSTS or host.endswith(".youtube.com") or host.endswith(".tiktok.com"):
        return {"url": url, "title": "", "text": "", "skipped": True}
    try:
        status, ctype, html = _fetch(url)
    except Exception:
        return None
    if status != 200:
        return None
    if "text/html" not in ctype and "text/plain" not in ctype:
        return None
    title, text = _clean_html(html)
    if len(text) < 200:
        return None
    return {"url": url, "title": title, "text": text[:limit_chars], "skipped": False}


async def fetch_many(urls, limit_chars: int = 800) -> list[dict]:
    """Fetch up to 3 URLs in parallel (asyncio.to_thread).

    Returns a list of {"url", "title", "text", "skipped"} dicts.
    YouTube/TikTok hosts are NOT fetched: they come back with text=""
    and skipped=True. Pages with <200 chars of cleaned text and pages
    that fail to fetch are omitted from the list.
    """
    urls = list(urls)[:3]
    results = await asyncio.gather(
        *(asyncio.to_thread(_fetch_one, u, limit_chars) for u in urls)
    )
    return [r for r in results if r is not None]


async def web_search(query: str, max_results: int = 5):
    url = "https://html.duckduckgo.com/html/?" + urllib.parse.urlencode({"q": query})
    status, _ct, text = await asyncio.to_thread(_fetch, url)
    if status != 200:
        return []
    soup = BeautifulSoup(text, "html.parser")
    out = []
    for a in soup.select(".result__a")[:max_results]:
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
    url2 = "https://lite.duckduckgo.com/lite/?" + urllib.parse.urlencode({"q": query})
    status, _ct, text2 = await asyncio.to_thread(_fetch, url2)
    if status != 200:
        return []
    soup2 = BeautifulSoup(text2, "html.parser")
    for a in soup2.select("a.result-link")[:max_results]:
        u = _resolve_ddg(a.get("href", ""))
        if not u:
            continue
        try:
            validate_url(u)
        except ValueError:
            continue
        out.append({"title": a.get_text(" ", strip=True), "url": u})
    return out


async def fetch_page_text(url: str, limit_chars: int = 4000) -> str:
    try:
        status, ctype, text = await asyncio.to_thread(_fetch, url)
    except Exception:
        return ""
    if status != 200:
        return ""
    if "text/html" not in ctype and "text/plain" not in ctype:
        return ""
    _title, cleaned = _clean_html(text)
    return cleaned[:limit_chars]
