"""Offline tests for web tool parsing, validation, and formatting."""

import ipaddress

import pytest
from pydantic import ValidationError

from xsh.config import Settings
from xsh.tools import web
from xsh.tools.web import FetchArgs, SearchArgs, WebTools, _html_to_markdown, _is_public_ip, _public_url, _search_sources


def _settings() -> Settings:
    return Settings(base_url="https://api.example/v1", model="m", api_key="k", search_api_key="s")


@pytest.mark.parametrize(
    "url",
    [
        "ftp://example.com",  # 非 http(s)
        "https://u:p@example.com/",  # 带凭据
        "https://example.com/a b",  # 空白
        "https://example.com/\\x",  # 反斜杠
        "https://exa%6dple.com/",  # 主机名转义
        "https://example.com:0/",  # 端口 0
    ],
)
def test_public_url_rejects(url: str) -> None:
    with pytest.raises(ValueError):
        _public_url(url)


def test_public_url_accepts_and_defaults_port() -> None:
    url, port = _public_url("https://example.com/path?q=1")
    assert url.hostname == "example.com"
    assert port == 443


@pytest.mark.parametrize("address", ["127.0.0.1", "10.0.0.1", "169.254.1.1", "224.0.0.1", "192.0.0.170"])
def test_private_or_special_ipv4_rejected(address: str) -> None:
    assert _is_public_ip(ipaddress.ip_address(address)) is False


def test_public_ipv4_accepted() -> None:
    assert _is_public_ip(ipaddress.ip_address("8.8.8.8")) is True


@pytest.mark.parametrize("address", ["::1", "fe80::1", "fc00::1"])
def test_non_public_ipv6_rejected(address: str) -> None:
    assert _is_public_ip(ipaddress.ip_address(address)) is False


def test_search_args_dedupe_and_validation() -> None:
    assert SearchArgs(queries=["a", "a", "b"]).queries == ["a", "b"]
    with pytest.raises(ValidationError):
        SearchArgs(queries=["  "])
    with pytest.raises(ValidationError):
        SearchArgs(queries=[])


def test_search_sources_merges_citations() -> None:
    payload = {
        "content": [
            {"type": "text", "citations": [{"url": "https://a.test", "cited_text": "excerpt A"}]},
            {
                "type": "web_search_tool_result",
                "content": [
                    {"type": "web_search_result", "url": "https://a.test", "title": "A", "page_age": "2024-01-01"},
                    {"type": "web_search_result", "url": "https://b.test", "title": "B"},
                ],
            },
        ]
    }
    sources = _search_sources(payload)
    assert [s["url"] for s in sources] == ["https://a.test", "https://b.test"]
    assert sources[0]["snippet"] == "excerpt A"
    assert sources[0]["date"] == "2024-01-01"


def test_search_sources_errors() -> None:
    with pytest.raises(ValueError, match="invalid content array"):
        _search_sources({"content": "nope"})
    with pytest.raises(ValueError, match="no web_search_tool_result"):
        _search_sources({"content": [{"type": "text"}]})


def test_html_to_markdown_strips_hidden_and_scripts() -> None:
    html = '<html><body><h1>Title</h1><script>bad()</script><p>keep</p><div style="display:none">gone</div></body></html>'
    text = _html_to_markdown(html)
    assert "Title" in text
    assert "keep" in text
    assert "bad()" not in text
    assert "gone" not in text


def test_search_formats_sources(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(WebTools, "_search", lambda self, body: [{"url": "https://a.test", "title": "A", "snippet": "snip"}])
    out = WebTools(_settings()).search(SearchArgs(queries=["q"]))
    assert "External, untrusted" in out
    assert "[A](https://a.test)" in out


def test_search_respects_max_results(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(WebTools, "_search", lambda self, body: [{"url": f"https://{i}.test", "title": f"T{i}"} for i in range(5)])
    out = WebTools(_settings()).search(SearchArgs(queries=["q"], max_results=2))
    assert out.count("](https://") == 2
    assert "first 2 sources" in out


def test_fetch_formats_and_truncates(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(web, "_fetch_page", lambda value: (value, 200, "text", "body text", False))
    out = WebTools(_settings()).fetch(FetchArgs(url="https://example.com"))
    assert "HTTP 200" in out and "body text" in out

    monkeypatch.setattr(web, "_fetch_page", lambda value: (value, 200, "text", "x" * 300_000, True))
    truncated = WebTools(_settings()).fetch(FetchArgs(url="https://example.com"))
    assert len(truncated) <= web._MAX_FETCH_OUTPUT_CHARS
    assert truncated.endswith(web._TRUNCATION_MARKER)
