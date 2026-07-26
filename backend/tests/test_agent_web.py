from __future__ import annotations

import asyncio
import socket
from datetime import datetime
from hashlib import sha256

import httpx
import pytest

from app.services.agent.integrations import web as agent_web


class _FakeNetworkStream:
    """Expose the peer metadata that httpcore attaches to real responses."""

    def __init__(self, address: str) -> None:
        self.address = address

    def get_extra_info(self, key: str):
        if key == "server_addr":
            return (self.address, 443)
        return None


def _peer_extensions(address: str = "93.184.216.34") -> dict[str, object]:
    return {"network_stream": _FakeNetworkStream(address)}


@pytest.mark.parametrize(
    "url",
    (
        "http://localhost/private",
        "http://127.0.0.1/private",
        "http://10.0.0.1/private",
        "http://169.254.169.254/latest/meta-data",
        "http://100.100.100.200/latest/meta-data",
        "http://224.0.0.1/multicast",
        "http://0.0.0.0/unspecified",
        "http://240.0.0.1/reserved",
        "http://[::1]/private",
        "http://metadata.google.internal/computeMetadata/v1",
    ),
)
def test_fetch_web_reference_rejects_non_public_targets_before_request(
    monkeypatch,
    url: str,
) -> None:
    real_client = httpx.Client

    def fail_if_requested(_request: httpx.Request) -> httpx.Response:
        raise AssertionError("Non-public targets must not reach the HTTP client.")

    transport = httpx.MockTransport(fail_if_requested)
    monkeypatch.setattr(
        agent_web.httpx,
        "Client",
        lambda **_kwargs: real_client(transport=transport),
    )

    assert agent_web._fetch_web_reference(url) is None


def test_fetch_web_reference_rejects_domain_when_any_dns_address_is_private(
    monkeypatch,
) -> None:
    real_client = httpx.Client

    def fake_getaddrinfo(
        _host: str,
        port: int,
        *_args,
        **_kwargs,
    ) -> list[tuple[int, int, int, str, tuple[str, int]]]:
        return [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port)),
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.8", port)),
        ]

    def fail_if_requested(_request: httpx.Request) -> httpx.Response:
        raise AssertionError("Unsafe DNS targets must not reach the HTTP client.")

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)
    transport = httpx.MockTransport(fail_if_requested)
    monkeypatch.setattr(
        agent_web.httpx,
        "Client",
        lambda **_kwargs: real_client(transport=transport),
    )

    assert agent_web._fetch_web_reference("https://public.example/resume") is None


def test_fetch_web_reference_revalidates_redirect_targets(monkeypatch) -> None:
    real_client = httpx.Client
    requested_urls: list[str] = []

    def fake_getaddrinfo(
        _host: str,
        port: int,
        *_args,
        **_kwargs,
    ) -> list[tuple[int, int, int, str, tuple[str, int]]]:
        return [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port)),
        ]

    def redirect_to_private(request: httpx.Request) -> httpx.Response:
        requested_urls.append(str(request.url))
        if request.url.host == "public.example":
            return httpx.Response(
                302,
                headers={"location": "http://127.0.0.1/private"},
                extensions=_peer_extensions(),
            )
        return httpx.Response(
            200,
            text="<html><body>" + ("private metadata " * 20) + "</body></html>",
            extensions=_peer_extensions(),
        )

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)
    transport = httpx.MockTransport(redirect_to_private)
    monkeypatch.setattr(
        agent_web.httpx,
        "Client",
        lambda **kwargs: real_client(
            transport=transport,
            follow_redirects=kwargs.get("follow_redirects", False),
        ),
    )

    assert agent_web._fetch_web_reference("https://public.example/start") is None
    assert requested_urls == ["https://public.example/start"]


def test_fetch_web_reference_records_final_public_redirect_url(monkeypatch) -> None:
    real_client = httpx.Client
    body = b"<html><body>" + (b"Public resume evidence. " * 10) + b"</body></html>"

    def fake_getaddrinfo(
        _host: str,
        port: int,
        *_args,
        **_kwargs,
    ) -> list[tuple[int, int, int, str, tuple[str, int]]]:
        return [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port)),
        ]

    def redirect_to_public(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/start":
            return httpx.Response(
                302,
                headers={"location": "/final"},
                extensions=_peer_extensions(),
            )
        return httpx.Response(
            200,
            content=body,
            headers={"content-type": "text/html; charset=utf-8"},
            extensions=_peer_extensions(),
        )

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)
    transport = httpx.MockTransport(redirect_to_public)
    monkeypatch.setattr(
        agent_web.httpx,
        "Client",
        lambda **kwargs: real_client(
            transport=transport,
            follow_redirects=kwargs.get("follow_redirects", False),
        ),
    )

    reference = agent_web._fetch_web_reference("https://public.example/start")

    assert reference is not None
    assert reference.final_url == "https://public.example/final"
    assert reference.status_code == 200
    assert reference.content_sha256 == sha256(body).hexdigest()


def test_fetch_web_reference_limits_redirect_count(monkeypatch) -> None:
    real_client = httpx.Client
    requested_urls: list[str] = []

    def fake_getaddrinfo(
        _host: str,
        port: int,
        *_args,
        **_kwargs,
    ) -> list[tuple[int, int, int, str, tuple[str, int]]]:
        return [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port)),
        ]

    def redirect_forever(request: httpx.Request) -> httpx.Response:
        requested_urls.append(str(request.url))
        hop = int(request.url.path.rsplit("/", 1)[-1])
        return httpx.Response(
            302,
            headers={"location": f"/hop/{hop + 1}"},
            extensions=_peer_extensions(),
        )

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)
    transport = httpx.MockTransport(redirect_forever)
    monkeypatch.setattr(
        agent_web.httpx,
        "Client",
        lambda **kwargs: real_client(
            transport=transport,
            follow_redirects=kwargs.get("follow_redirects", False),
        ),
    )

    assert agent_web._fetch_web_reference("https://public.example/hop/0") is None
    assert len(requested_urls) == agent_web.MAX_WEB_REDIRECTS + 1


def test_fetch_web_reference_allows_public_target_and_records_metadata(
    monkeypatch,
) -> None:
    real_client = httpx.Client
    body = (
        b"<html><head><title>Public resume guide</title></head><body>"
        + (b"Evidence-based resume guidance for applicants. " * 8)
        + b"</body></html>"
    )

    def fake_getaddrinfo(
        _host: str,
        port: int,
        *_args,
        **_kwargs,
    ) -> list[tuple[int, int, int, str, tuple[str, int]]]:
        return [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port)),
        ]

    transport = httpx.MockTransport(
        lambda _request: httpx.Response(
            200,
            content=body,
            headers={"content-type": "text/html; charset=utf-8"},
            extensions=_peer_extensions(),
        ),
    )
    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)
    monkeypatch.setattr(
        agent_web.httpx,
        "Client",
        lambda **_kwargs: real_client(transport=transport),
    )

    reference = agent_web._fetch_web_reference(
        "https://public.example/resume-guide",
    )

    assert reference is not None
    assert reference.final_url == "https://public.example/resume-guide"
    assert reference.status_code == 200
    assert reference.content_sha256 == sha256(body).hexdigest()
    assert datetime.fromisoformat(reference.fetched_at.replace("Z", "+00:00"))


def test_fetch_web_reference_rejects_private_connected_peer_before_body_read(
    monkeypatch,
) -> None:
    real_client = httpx.Client

    class UnreadableStream(httpx.SyncByteStream):
        def __iter__(self):
            raise AssertionError("A private peer response body must not be read.")

    def fake_getaddrinfo(
        _host: str,
        port: int,
        *_args,
        **_kwargs,
    ) -> list[tuple[int, int, int, str, tuple[str, int]]]:
        return [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port)),
        ]

    transport = httpx.MockTransport(
        lambda _request: httpx.Response(
            200,
            stream=UnreadableStream(),
            extensions=_peer_extensions("10.0.0.8"),
        ),
    )
    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)
    monkeypatch.setattr(
        agent_web.httpx,
        "Client",
        lambda **_kwargs: real_client(transport=transport),
    )

    assert agent_web._fetch_web_reference("https://public.example/rebound") is None


def test_fetch_web_reference_rejects_missing_connected_peer_before_body_read(
    monkeypatch,
) -> None:
    real_client = httpx.Client

    class UnreadableStream(httpx.SyncByteStream):
        def __iter__(self):
            raise AssertionError("An unverifiable peer response body must not be read.")

    def fake_getaddrinfo(
        _host: str,
        port: int,
        *_args,
        **_kwargs,
    ) -> list[tuple[int, int, int, str, tuple[str, int]]]:
        return [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port)),
        ]

    transport = httpx.MockTransport(
        lambda _request: httpx.Response(200, stream=UnreadableStream()),
    )
    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)
    monkeypatch.setattr(
        agent_web.httpx,
        "Client",
        lambda **_kwargs: real_client(transport=transport),
    )

    assert agent_web._fetch_web_reference("https://public.example/no-peer") is None


def test_fetch_web_reference_stops_reading_at_response_limit(monkeypatch) -> None:
    real_client = httpx.Client
    prefix = (
        b"<html><head><title>Bounded page</title></head><body>"
        + (b"Public resume evidence. " * 8)
        + b"</body></html>"
    )
    second_chunk = b"x" * agent_web.FETCH_MAX_BYTES

    class GuardedStream(httpx.SyncByteStream):
        def __init__(self) -> None:
            self.chunks_read = 0

        def __iter__(self):
            self.chunks_read += 1
            yield prefix
            self.chunks_read += 1
            yield second_chunk
            raise AssertionError("The response body limit was not enforced.")

    stream = GuardedStream()

    def fake_getaddrinfo(
        _host: str,
        port: int,
        *_args,
        **_kwargs,
    ) -> list[tuple[int, int, int, str, tuple[str, int]]]:
        return [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port)),
        ]

    transport = httpx.MockTransport(
        lambda _request: httpx.Response(
            200,
            stream=stream,
            headers={"content-type": "text/html; charset=utf-8"},
            extensions=_peer_extensions(),
        ),
    )
    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)
    monkeypatch.setattr(
        agent_web.httpx,
        "Client",
        lambda **_kwargs: real_client(transport=transport),
    )

    reference = agent_web._fetch_web_reference("https://public.example/large")

    expected_body = (prefix + second_chunk)[: agent_web.FETCH_MAX_BYTES]
    assert reference is not None
    assert stream.chunks_read == 2
    assert reference.content_sha256 == sha256(expected_body).hexdigest()


def test_search_web_results_revalidates_redirect_targets(monkeypatch) -> None:
    real_client = httpx.Client
    requested_urls: list[str] = []

    def fake_getaddrinfo(
        _host: str,
        port: int,
        *_args,
        **_kwargs,
    ) -> list[tuple[int, int, int, str, tuple[str, int]]]:
        return [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port)),
        ]

    def redirect_to_private(request: httpx.Request) -> httpx.Response:
        requested_urls.append(str(request.url))
        if request.url.host == "search.example":
            return httpx.Response(
                302,
                headers={"location": "http://127.0.0.1/private-search"},
                extensions=_peer_extensions(),
            )
        return httpx.Response(
            200,
            text=(
                '<a class="result__a" href="https://public.example/result">'
                "Public result</a>"
            ),
            extensions=_peer_extensions(),
        )

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)
    monkeypatch.setattr(
        agent_web,
        "SEARCH_ENDPOINTS",
        ("https://search.example/?q={query}",),
    )
    transport = httpx.MockTransport(redirect_to_private)
    monkeypatch.setattr(
        agent_web.httpx,
        "Client",
        lambda **kwargs: real_client(
            transport=transport,
            follow_redirects=kwargs.get("follow_redirects", False),
        ),
    )

    results, error = agent_web._search_web_results("resume")

    assert results == []
    assert error
    assert requested_urls == ["https://search.example/?q=resume"]


def test_async_fetch_web_reference_revalidates_redirect_targets(monkeypatch) -> None:
    real_client = httpx.AsyncClient
    requested_urls: list[str] = []

    def fake_getaddrinfo(
        _host: str,
        port: int,
        *_args,
        **_kwargs,
    ) -> list[tuple[int, int, int, str, tuple[str, int]]]:
        return [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port)),
        ]

    def redirect_to_private(request: httpx.Request) -> httpx.Response:
        requested_urls.append(str(request.url))
        return httpx.Response(
            302,
            headers={"location": "http://127.0.0.1/private"},
            extensions=_peer_extensions(),
        )

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)
    transport = httpx.MockTransport(redirect_to_private)
    monkeypatch.setattr(
        agent_web.httpx,
        "AsyncClient",
        lambda **kwargs: real_client(
            transport=transport,
            follow_redirects=kwargs.get("follow_redirects", False),
        ),
    )

    reference = asyncio.run(
        agent_web._async_fetch_web_reference("https://public.example/start"),
    )

    assert reference is None
    assert requested_urls == ["https://public.example/start"]


def test_async_fetch_web_reference_accepts_public_connected_peer(
    monkeypatch,
) -> None:
    real_client = httpx.AsyncClient
    body = (
        b"<html><head><title>Public peer</title></head><body>"
        + (b"Public resume evidence. " * 8)
        + b"</body></html>"
    )

    def fake_getaddrinfo(
        _host: str,
        port: int,
        *_args,
        **_kwargs,
    ) -> list[tuple[int, int, int, str, tuple[str, int]]]:
        return [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port)),
        ]

    transport = httpx.MockTransport(
        lambda _request: httpx.Response(
            200,
            content=body,
            headers={"content-type": "text/html; charset=utf-8"},
            extensions=_peer_extensions(),
        ),
    )
    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)
    monkeypatch.setattr(
        agent_web.httpx,
        "AsyncClient",
        lambda **_kwargs: real_client(transport=transport),
    )

    reference = asyncio.run(
        agent_web._async_fetch_web_reference(
            "https://public.example/public-peer",
        ),
    )

    assert reference is not None
    assert reference.content_sha256 == sha256(body).hexdigest()


def test_async_fetch_web_reference_rejects_private_connected_peer_before_body_read(
    monkeypatch,
) -> None:
    real_client = httpx.AsyncClient

    class UnreadableStream(httpx.AsyncByteStream):
        async def __aiter__(self):
            raise AssertionError("A private peer response body must not be read.")
            yield b""  # pragma: no cover

    def fake_getaddrinfo(
        _host: str,
        port: int,
        *_args,
        **_kwargs,
    ) -> list[tuple[int, int, int, str, tuple[str, int]]]:
        return [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port)),
        ]

    transport = httpx.MockTransport(
        lambda _request: httpx.Response(
            200,
            stream=UnreadableStream(),
            extensions=_peer_extensions("10.0.0.8"),
        ),
    )
    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)
    monkeypatch.setattr(
        agent_web.httpx,
        "AsyncClient",
        lambda **_kwargs: real_client(transport=transport),
    )

    reference = asyncio.run(
        agent_web._async_fetch_web_reference(
            "https://public.example/rebound",
        ),
    )

    assert reference is None


def test_async_search_web_results_revalidates_redirect_targets(monkeypatch) -> None:
    real_client = httpx.AsyncClient
    requested_urls: list[str] = []

    def fake_getaddrinfo(
        _host: str,
        port: int,
        *_args,
        **_kwargs,
    ) -> list[tuple[int, int, int, str, tuple[str, int]]]:
        return [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port)),
        ]

    def redirect_to_private(request: httpx.Request) -> httpx.Response:
        requested_urls.append(str(request.url))
        return httpx.Response(
            302,
            headers={"location": "http://127.0.0.1/private-search"},
            extensions=_peer_extensions(),
        )

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)
    monkeypatch.setattr(
        agent_web,
        "SEARCH_ENDPOINTS",
        ("https://search.example/?q={query}",),
    )
    transport = httpx.MockTransport(redirect_to_private)
    monkeypatch.setattr(
        agent_web.httpx,
        "AsyncClient",
        lambda **kwargs: real_client(
            transport=transport,
            follow_redirects=kwargs.get("follow_redirects", False),
        ),
    )

    results, error = asyncio.run(agent_web._async_search_web_results("resume"))

    assert results == []
    assert error
    assert requested_urls == ["https://search.example/?q=resume"]


def test_search_web_reference_preserves_fetched_evidence_metadata(
    monkeypatch,
) -> None:
    search_result = agent_web.WebSearchResult(
        title="Search title",
        url="https://public.example/redirect",
        excerpt="Search snippet",
    )
    fetched_at = "2026-07-26T08:00:00Z"
    content_sha256 = "a" * 64

    monkeypatch.setattr(
        agent_web,
        "_search_web_results",
        lambda _query: ([search_result], None),
    )
    monkeypatch.setattr(
        agent_web,
        "_fetch_web_reference",
        lambda _url: agent_web.WebReference(
            title="Fetched title",
            excerpt="Fetched evidence " * 10,
            final_url="https://public.example/final",
            status_code=200,
            fetched_at=fetched_at,
            content_sha256=content_sha256,
        ),
    )

    result, result_count, error = agent_web._search_web_reference("resume")

    assert error is None
    assert result_count == 1
    assert result is not None
    assert result.url == "https://public.example/final"
    assert result.final_url == "https://public.example/final"
    assert result.status_code == 200
    assert result.fetched_at == fetched_at
    assert result.content_sha256 == content_sha256
