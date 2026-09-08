import asyncio
import ipaddress
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import anyio
import httpx
import pytest

from app.services.agent.integrations import web_network
from app.services.agent.integrations.web_network import PublicWebTransport


def test_fetch_does_not_send_to_rebound_loopback(monkeypatch) -> None:
    hits: list[str] = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            hits.append(self.path)
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"isolated-audit-test")

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    real_getaddrinfo = socket.getaddrinfo
    real_connect_tcp = anyio.connect_tcp
    resolutions: list[str] = []
    connections: list[str] = []

    def changing_dns(host, port, *args, **kwargs):
        if host in {"rebound.example", b"rebound.example"}:
            host = "93.184.216.34" if not resolutions else "127.0.0.1"
            resolutions.append(host)
        return real_getaddrinfo(host, port, *args, **kwargs)

    async def isolated_connect_tcp(remote_host, remote_port, **kwargs):
        connections.append(remote_host)
        try:
            address = ipaddress.ip_address(remote_host)
        except ValueError:
            pass
        else:
            if address.is_global:
                raise OSError("Public connection disabled by the isolated test")
        return await real_connect_tcp(remote_host, remote_port, **kwargs)

    monkeypatch.setattr(socket, "getaddrinfo", changing_dns)
    monkeypatch.setattr(anyio, "connect_tcp", isolated_connect_tcp)

    async def fetch() -> None:
        async with httpx.AsyncClient(
            transport=PublicWebTransport(), trust_env=False, timeout=1
        ) as client:
            try:
                await client.get(f"http://rebound.example:{server.server_port}/audit")
            except httpx.ConnectError:
                pass

    try:
        asyncio.run(fetch())
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=2)

    assert resolutions == ["93.184.216.34"]
    assert connections == ["93.184.216.34"]
    assert hits == []


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/private",
        "http://[::1]/private",
        "http://10.0.0.1/private",
        "http://169.254.169.254/latest/meta-data",
        "http://100.100.100.200/latest/meta-data",
        "http://198.18.0.157/fake-ip",
        "http://224.0.0.1/multicast",
        "http://[ff02::1]/multicast",
        "http://[::ffff:224.0.0.1]/multicast",
        "http://[::ffff:127.0.0.1]/private",
        "http://[::ffff:198.18.0.1]/fake-ip",
        "http://localhost/private",
        "http://local.localhost/private",
        "http://metadata.google.internal/private",
        "http://instance-data.ec2.internal/private",
        "http://0.0.0.0/private",
        "file:///etc/passwd",
        "https://user:password@example.com/private",
        "https://example.com:invalid/private",
    ],
)
def test_rejects_unsafe_targets_without_dns(monkeypatch, url: str) -> None:
    def unexpected_lookup(*args, **kwargs):
        pytest.fail("Unsafe URL reached DNS")

    monkeypatch.setattr(socket, "getaddrinfo", unexpected_lookup)
    assert not web_network.is_public_web_url(url)
    assert web_network.safe_web_target_addresses(url) is None


@pytest.mark.parametrize(
    ("addresses", "expected"),
    [
        (["93.184.216.34", "1.1.1.1"], ("93.184.216.34", "1.1.1.1")),
        (["1.1.1.1", "93.184.216.34", "1.1.1.1"], ("1.1.1.1", "93.184.216.34")),
        (["93.184.216.34", "127.0.0.1"], None),
        (["93.184.216.34", "10.0.0.1"], None),
        (["93.184.216.34", "224.0.0.1"], None),
        (["93.184.216.34", "ff02::1"], None),
        (["93.184.216.34", "::ffff:224.0.0.1"], None),
        (["198.18.0.157"], ("198.18.0.157",)),
        (["2606:4700:4700::1111"], ("2606:4700:4700::1111",)),
        ([], None),
    ],
)
def test_resolves_all_addresses_before_allowing_connections(
    monkeypatch, addresses, expected
) -> None:
    def lookup(*args, **kwargs):
        return [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, 443))
            for address in addresses
        ]

    monkeypatch.setattr(socket, "getaddrinfo", lookup)
    assert web_network.safe_web_target_addresses("https://jobs.example/a") == expected


def test_keeps_original_origins_for_tls_cookies_and_urls(monkeypatch) -> None:
    transports = []
    calls = []

    class RecordingTransport(httpx.AsyncBaseTransport):
        def __init__(self, **kwargs):
            transports.append(self)
            self.closed = False

        async def handle_async_request(self, request):
            calls.append((self, request))
            return httpx.Response(
                200,
                headers={
                    "Set-Cookie": "session=abc; Domain=jobs.example; Path=/; Secure"
                },
                content=b"ok",
            )

        async def aclose(self):
            self.closed = True

    monkeypatch.setattr(httpx, "AsyncHTTPTransport", RecordingTransport)
    monkeypatch.setattr(
        web_network, "safe_web_target_addresses", lambda url: ("93.184.216.34",)
    )

    async def fetch() -> None:
        async with httpx.AsyncClient(
            transport=PublicWebTransport(), trust_env=False
        ) as client:
            first = await client.get("https://jobs.example:8443/a?x=1")
            second = await client.get("https://jobs.example:8443/b")
            third = await client.get("https://other.example:8443/c")
            assert str(first.url) == "https://jobs.example:8443/a?x=1"
            assert str(second.url) == "https://jobs.example:8443/b"
            assert str(third.url) == "https://other.example:8443/c"

    asyncio.run(fetch())
    assert len(transports) == 2
    assert all(transport.closed for transport in transports)
    first, second, third = [request for _, request in calls]
    assert str(first.url) == "https://93.184.216.34:8443/a?x=1"
    assert first.headers["Host"] == "jobs.example:8443"
    assert first.extensions["sni_hostname"] == "jobs.example"
    assert second.headers["Cookie"] == "session=abc"
    assert "Cookie" not in third.headers
    assert third.headers["Host"] == "other.example:8443"
    assert third.extensions["sni_hostname"] == "other.example"
    assert calls[0][0] is calls[1][0]
    assert calls[0][0] is not calls[2][0]


def test_tries_other_validated_addresses_before_sending_body(monkeypatch) -> None:
    addresses = []
    bodies = []

    class AddressTransport(httpx.AsyncBaseTransport):
        def __init__(self, **kwargs):
            pass

        async def handle_async_request(self, request):
            addresses.append(request.url.host)
            if request.url.host == "93.184.216.34":
                raise httpx.ConnectError("Connection unavailable")
            bodies.append(await request.aread())
            return httpx.Response(200, content=b"ok")

    monkeypatch.setattr(httpx, "AsyncHTTPTransport", AddressTransport)
    monkeypatch.setattr(
        web_network,
        "safe_web_target_addresses",
        lambda url: ("93.184.216.34", "1.1.1.1"),
    )

    async def fetch() -> None:
        async with httpx.AsyncClient(
            transport=PublicWebTransport(), trust_env=False
        ) as client:
            response = await client.post(
                "https://jobs.example/search", content=b"q=react"
            )
            assert response.text == "ok"

    asyncio.run(fetch())
    assert addresses == ["93.184.216.34", "1.1.1.1"]
    assert bodies == [b"q=react"]


def test_redirects_revalidate_dns_and_keep_relative_urls_and_cookies(
    monkeypatch,
) -> None:
    hosts = []
    lookups = []
    requests = []

    def lookup(url):
        lookups.append(url)
        if httpx.URL(url).host == "private.example":
            return None
        return ("93.184.216.34",)

    class RedirectTransport(httpx.AsyncBaseTransport):
        def __init__(self, **kwargs):
            pass

        async def handle_async_request(self, request):
            requests.append(request)
            hosts.append(request.headers["Host"])
            if request.url.path == "/start":
                return httpx.Response(
                    302,
                    headers={"Location": "/middle", "Set-Cookie": "visit=1; Path=/"},
                )
            return httpx.Response(
                302, headers={"Location": "http://private.example/blocked"}
            )

    monkeypatch.setattr(httpx, "AsyncHTTPTransport", RedirectTransport)
    monkeypatch.setattr(web_network, "safe_web_target_addresses", lookup)

    async def fetch() -> None:
        async with httpx.AsyncClient(
            transport=PublicWebTransport(), trust_env=False, follow_redirects=True
        ) as client:
            with pytest.raises(httpx.ConnectError, match="not public"):
                await client.get("https://jobs.example/start")

    asyncio.run(fetch())
    assert hosts == ["jobs.example", "jobs.example"]
    assert requests[1].headers["Cookie"] == "visit=1"
    assert lookups == [
        "https://jobs.example/start",
        "https://jobs.example/middle",
        "http://private.example/blocked",
    ]
