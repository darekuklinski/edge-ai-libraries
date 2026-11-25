import asyncio
from email.message import Message

import httpx
import pytest
from langchain_core.documents import Document

from app import read_only_web, web_search

RULES = [
    {"kind": "url", "effect": "allow", "value": "https://example.com/article"},
    {"kind": "url", "effect": "allow", "value": "https://example.org/article"},
]


def test_search_uses_bing_and_fetches_results_read_only(monkeypatch):
    seen = []

    def handle(request):
        assert request.method == "GET"
        assert request.url.host == "www.bing.com"
        assert request.url.params["q"] == "Apollo 11"
        return httpx.Response(200, text=(
            "<rss><channel><item><link>https://example.com/article</link></item>"
            "<item><link>https://example.org/article</link></item></channel></rss>"
        ))

    def fetch(url):
        seen.append(url)
        if "example.org" in url:
            raise read_only_web.PageFetchError("unavailable")
        return Document(page_content="A lunar mission.", metadata={"source": url})

    monkeypatch.setattr(web_search, "fetch_read_only_page", fetch)

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            return await web_search.search_web("Apollo 11", client, RULES)

    result = asyncio.run(run())
    assert seen == ["https://example.com/article", "https://example.org/article"]
    assert result.documents[0].page_content == "A lunar mission."
    assert result.failures == 1


def test_direct_url_never_contacts_search_provider(monkeypatch):
    monkeypatch.setattr(web_search, "fetch_read_only_page", lambda url: Document(page_content="page", metadata={"source": url}))

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(
            lambda _request: pytest.fail("Search provider must not be called")
        )) as client:
            return await web_search.search_web("https://example.com/article", client, RULES)

    assert asyncio.run(run()).documents[0].metadata["source"] == "https://example.com/article"


def test_search_never_fetches_disallowed_results(monkeypatch):
    seen = []
    monkeypatch.setattr(web_search, "fetch_read_only_page", lambda url: seen.append(url) or Document(page_content="ok", metadata={"source": url}))
    rules = RULES + [{"kind": "url", "effect": "deny", "value": "https://example.org/article"}]

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _request: httpx.Response(
            200, text="<rss><channel><item><link>https://example.org/article</link></item><item><link>https://example.com/article</link></item><item><link>https://other.example/</link></item></channel></rss>"
        ))) as client:
            return await web_search.search_web("Apollo 11", client, rules)

    result = asyncio.run(run())
    assert seen == ["https://example.com/article"]
    assert result.failures == 2


def test_search_errors_are_reported():
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(
            lambda _request: httpx.Response(302, headers={"location": "https://example.com/"})
        ), follow_redirects=False) as client:
            await web_search.search_web("example", client, RULES)

    with pytest.raises(web_search.WebSearchError, match="failed"):
        asyncio.run(run())


def test_oversized_search_response_is_rejected():
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(
            lambda _request: httpx.Response(200, content=b"x" * 1_000_001)
        )) as client:
            await web_search.search_web("example", client, RULES)

    with pytest.raises(web_search.WebSearchError, match="size limit"):
        asyncio.run(run())


@pytest.mark.parametrize("url", [
    "http://example.com/", "https://127.0.0.1/", "https://user:pass@example.com/",
    "https://example.com/?action=submit", "https://example.com/#fragment",
    "https://example.com:8443/", "https://localhost/",
])
def test_page_fetch_rejects_unsafe_urls(url):
    with pytest.raises(read_only_web.PageFetchError):
        read_only_web.fetch_read_only_page(url)


def test_page_fetch_rejects_dns_with_private_addresses(monkeypatch):
    monkeypatch.setattr(read_only_web.socket, "getaddrinfo", lambda *_args, **_kwargs: [
        (None, None, None, None, ("93.184.216.34", 443)),
        (None, None, None, None, ("127.0.0.1", 443)),
    ])
    with pytest.raises(read_only_web.PageFetchError):
        read_only_web.fetch_read_only_page("https://example.com/")


def test_page_fetch_pins_public_ip_uses_get_and_ignores_forms(monkeypatch):
    monkeypatch.setattr(read_only_web.socket, "getaddrinfo", lambda *_args, **_kwargs: [
        (None, None, None, None, ("93.184.216.34", 443)),
    ])
    calls = []

    class Response:
        status = 200
        headers = Message()
        chunks = [b"<p>Public text</p><form>Form data</form><script>hidden</script>", b""]

        def getheader(self, _name, _default):
            return "text/html"

        def read1(self, _limit):
            return self.chunks.pop(0)

    class Connection:
        def __init__(self, host, address):
            calls.append((host, address))

        def request(self, method, path, headers):
            calls.append((method, path, headers))

        def getresponse(self):
            return Response()

        def close(self):
            pass

    monkeypatch.setattr(read_only_web, "_PinnedHTTPSConnection", Connection)
    document = read_only_web.fetch_read_only_page("https://example.com/article")
    assert calls[0] == ("example.com", "93.184.216.34")
    assert calls[1][0:2] == ("GET", "/article")
    assert "Cookie" not in calls[1][2]
    assert document.page_content == "Public text"


def test_page_fetch_rejects_redirect_without_following(monkeypatch):
    monkeypatch.setattr(read_only_web.socket, "getaddrinfo", lambda *_args, **_kwargs: [
        (None, None, None, None, ("93.184.216.34", 443)),
    ])
    calls = []

    class Response:
        status = 302
        def getheader(self, _name, _default):
            return "text/html"

    class Connection:
        def __init__(self, _host, _address):
            pass
        def request(self, method, path, headers):
            calls.append((method, path))
        def getresponse(self):
            return Response()
        def close(self):
            pass

    monkeypatch.setattr(read_only_web, "_PinnedHTTPSConnection", Connection)
    with pytest.raises(read_only_web.PageFetchError, match="HTTP 302"):
        read_only_web.fetch_read_only_page("https://example.com/")
    assert calls == [("GET", "/")]


def test_refinement_cannot_add_external_terms():
    assert web_search.validated_refinement("apollo 11 mission", "Apollo mission") == "apollo mission"
    assert web_search.validated_refinement("apollo 11 mission", "Apollo secret") is None
    assert web_search.validated_refinement("apollo 11 mission", "Apollo 11 mission") is None
