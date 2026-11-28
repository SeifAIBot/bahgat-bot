"""Web search: SSRF guard, DDG redirect resolution, prompt formatting."""
import pytest

from bahgat import search


class TestValidateUrl:
    def test_blocks_private_ips(self):
        for bad in ("https://127.0.0.1/", "https://10.0.0.5/x",
                    "https://192.168.1.1/", "https://169.254.169.254/meta",
                    "https://[::1]/"):
            with pytest.raises(ValueError):
                search.validate_url(bad)

    def test_blocks_bad_input(self):
        for bad in ("", "ftp://example.com/x", "-O", "https:///nohost",
                    "https://user:pw@example.com/"):
            with pytest.raises(ValueError):
                search.validate_url(bad)

    def test_http_only_for_ddg(self):
        with pytest.raises(ValueError):
            search.validate_url("http://example.com/")

    def test_unresolvable_host(self):
        with pytest.raises(ValueError):
            search.validate_url("https://nonexistent-host-zzzz.invalid/")


class TestDdgRedirect:
    def test_uddg_resolved(self):
        href = "/l/?uddg=https%3A%2F%2Fexample.com%2Fpage&rut=x"
        assert search._resolve_ddg(href) == "https://example.com/page"

    def test_protocol_relative(self):
        assert search._resolve_ddg("//example.com/x") == "https://example.com/x"

    def test_empty(self):
        assert search._resolve_ddg("") == ""


class TestFormatResults:
    def test_numbered_sources(self):
        results = [{"title": "t1", "url": "https://a.com"},
                    {"title": "t2", "url": "https://b.com"}]
        out = search.format_results_for_prompt(results)
        assert "[1] t1" in out and "[2] t2" in out

    def test_page_text_included(self):
        results = [{"title": "t1", "url": "https://a.com"}]
        pages = [{"url": "https://a.com", "text": "محتوى الصفحة " * 50}]
        out = search.format_results_for_prompt(results, pages)
        assert "محتوى الصفحة" in out
