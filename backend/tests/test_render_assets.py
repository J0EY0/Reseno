import asyncio

import httpx

from app.services import render_assets


def test_image_fetch_follows_redirects_without_browser_credentials(monkeypatch):
    requests = []

    def respond(request):
        requests.append(request)
        if request.url.path == "/avatar":
            return httpx.Response(302, headers={"location": "/image.png"})
        return httpx.Response(
            200, content=b"png-bytes", headers={"content-type": "image/png"}
        )

    monkeypatch.setattr(
        render_assets, "PublicWebTransport", lambda: httpx.MockTransport(respond)
    )
    result = asyncio.run(
        render_assets._fetch_public_image("https://images.example/avatar")
    )
    assert result == (b"png-bytes", "image/png")
    assert [request.url.path for request in requests] == ["/avatar", "/image.png"]
    assert all(
        "authorization" not in request.headers and "cookie" not in request.headers
        for request in requests
    )


def test_image_fetch_rejects_non_image_responses(monkeypatch):
    monkeypatch.setattr(
        render_assets,
        "PublicWebTransport",
        lambda: httpx.MockTransport(
            lambda request: httpx.Response(
                200, content=b"secret", headers={"content-type": "text/plain"}
            )
        ),
    )
    assert (
        asyncio.run(render_assets._fetch_public_image("https://images.example/avatar"))
        is None
    )


def test_image_fetch_stops_oversized_responses(monkeypatch):
    monkeypatch.setattr(render_assets, "MAX_RENDER_IMAGE_BYTES", 4)
    monkeypatch.setattr(
        render_assets,
        "PublicWebTransport",
        lambda: httpx.MockTransport(
            lambda request: httpx.Response(
                200, content=b"12345", headers={"content-type": "image/png"}
            )
        ),
    )
    assert (
        asyncio.run(render_assets._fetch_public_image("https://images.example/avatar"))
        is None
    )


def test_image_fetch_rejects_private_redirect_before_connecting(monkeypatch):
    from app.services.agent.integrations import web_network

    requests = []

    class PublicServer(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request):
            requests.append(request)
            return httpx.Response(
                302, headers={"location": "http://127.0.0.1/private.png"}
            )

    original = web_network.safe_web_target_addresses
    monkeypatch.setattr(
        web_network,
        "safe_web_target_addresses",
        lambda url: (
            ("93.184.216.34",)
            if httpx.URL(url).host == "images.example"
            else original(url)
        ),
    )
    monkeypatch.setattr(
        web_network.httpx, "AsyncHTTPTransport", lambda **kwargs: PublicServer()
    )
    assert (
        asyncio.run(render_assets._fetch_public_image("https://images.example/avatar"))
        is None
    )
    assert len(requests) == 1
    assert requests[0].url.host == "93.184.216.34"


def test_image_fetch_rejects_private_dns_before_connecting(monkeypatch):
    from app.services.agent.integrations import web_network

    monkeypatch.setattr(
        web_network.socket,
        "getaddrinfo",
        lambda *args, **kwargs: [(2, 1, 6, "", ("127.0.0.1", 80))],
    )
    assert (
        asyncio.run(render_assets._fetch_public_image("https://images.example/avatar"))
        is None
    )
