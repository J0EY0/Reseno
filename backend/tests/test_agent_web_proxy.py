import asyncio
import ipaddress
import socket
from contextlib import asynccontextmanager, suppress
from urllib.parse import urlsplit

import pytest

from app.services.agent.integrations import web_network, web_proxy
from app.services.agent.integrations.web_proxy import PublicWebProxy


def _request(hostname: str, port: int = 443) -> bytes:
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        encoded = hostname.encode("ascii")
        target = b"\x03" + bytes((len(encoded),)) + encoded
    else:
        target = bytes((1 if address.version == 4 else 4,)) + address.packed
    return b"\x05\x01\x00" + target + port.to_bytes(2, "big")


@asynccontextmanager
async def _client():
    proxy = PublicWebProxy()
    address = await proxy.start()
    reader, writer = await asyncio.open_connection("127.0.0.1", urlsplit(address).port)
    try:
        yield proxy, reader, writer
    finally:
        writer.close()
        await writer.wait_closed()
        await asyncio.wait_for(proxy.close(), 2)


async def _negotiate(reader, writer) -> None:
    writer.write(b"\x05\x01\x00")
    await writer.drain()
    assert await asyncio.wait_for(reader.readexactly(2), 2) == b"\x05\x00"


@pytest.mark.parametrize("greeting", [b"\x04\x01\x00", b"\x05\x00", b"\x05\x01\x02"])
def test_proxy_rejects_invalid_authentication(greeting) -> None:
    async def scenario():
        async with _client() as (_, reader, writer):
            writer.write(greeting)
            await writer.drain()
            response = await asyncio.wait_for(reader.read(), 2)
            assert response == (b"\x05\xff" if greeting[-1] == 2 else b"")

    asyncio.run(scenario())


@pytest.mark.parametrize(
    ("packet", "status"),
    [
        (b"\x04\x01\x00\x01", 1),
        (b"\x05\x02\x00\x01", 7),
        (b"\x05\x03\x00\x01", 7),
        (b"\x05\x01\x01\x01", 1),
        (b"\x05\x01\x00\x05", 8),
        (b"\x05\x01\x00\x03\x00", 8),
        (b"\x05\x01\x00\x03\xfe", 8),
        (b"\x05\x01\x00\x03\x01\xff", 8),
        (_request("a" * 64 + ".example"), 8),
        (_request("public.example/private"), 8),
        (_request("public..example"), 8),
        (_request("public.example", 0), 1),
    ],
)
def test_proxy_rejects_malformed_or_unsupported_requests(packet, status) -> None:
    async def scenario():
        async with _client() as (_, reader, writer):
            await _negotiate(reader, writer)
            writer.write(packet)
            await writer.drain()
            reply = await asyncio.wait_for(reader.readexactly(10), 2)
            assert reply[:3] == bytes((5, status, 0))
            assert await asyncio.wait_for(reader.read(), 2) == b""

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "hostname",
    [
        "127.0.0.1",
        "::1",
        "169.254.169.254",
        "198.18.0.1",
        "localhost",
        "private.example",
    ],
)
def test_proxy_rejects_private_and_literal_fake_ip_destinations(monkeypatch, hostname):
    monkeypatch.setattr(
        web_network.socket,
        "getaddrinfo",
        lambda *args, **kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.1", 443))
        ],
    )

    async def scenario():
        async with _client() as (_, reader, writer):
            await _negotiate(reader, writer)
            writer.write(_request(hostname))
            await writer.drain()
            reply = await asyncio.wait_for(reader.readexactly(10), 2)
            assert reply[1] == 2

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "resolved_ip", ["93.184.216.34", "198.18.0.42", "2606:4700:4700::1111"]
)
def test_proxy_preserves_bidirectional_bytes_and_half_close(monkeypatch, resolved_ip):
    connections = []
    dns_queries = []
    payload = b"binary request\x00\xff" * 10_000
    response = b"binary response\x00\xfe" * 10_000
    original_connect = asyncio.open_connection

    def resolve(host, port, **kwargs):
        dns_queries.append(host)
        family = socket.AF_INET6 if ":" in resolved_ip else socket.AF_INET
        return [(family, socket.SOCK_STREAM, 6, "", (resolved_ip, port))]

    async def scenario():
        delivered = asyncio.get_running_loop().create_future()

        async def serve(reader, writer):
            try:
                received = await reader.read()
                delivered.set_result(received)
                writer.write(response)
                await writer.drain()
            finally:
                writer.close()
                await writer.wait_closed()

        server = await asyncio.start_server(serve, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]

        async def connect(host, target_port, **kwargs):
            if host == resolved_ip:
                connections.append((host, target_port))
                return await original_connect("127.0.0.1", port)
            return await original_connect(host, target_port, **kwargs)

        monkeypatch.setattr(web_network.socket, "getaddrinfo", resolve)
        monkeypatch.setattr(web_proxy.asyncio, "open_connection", connect)
        try:
            async with _client() as (_, reader, writer):
                await _negotiate(reader, writer)
                writer.write(_request("public.example", port))
                await writer.drain()
                assert (await asyncio.wait_for(reader.readexactly(10), 2))[1] == 0
                writer.write(payload)
                await writer.drain()
                writer.write_eof()
                assert await asyncio.wait_for(reader.read(), 2) == response
                assert await delivered == payload
        finally:
            server.close()
            await server.wait_closed()
        assert dns_queries == ["public.example"]
        assert connections == [(resolved_ip, port)]

    asyncio.run(scenario())


def test_proxy_dns_rebinding_never_reaches_loopback(monkeypatch) -> None:
    hits = []
    resolutions = []
    connections = []
    original_dns = socket.getaddrinfo
    original_connect = asyncio.open_connection

    def resolve(host, port, *args, **kwargs):
        if host == "rebound.example":
            host = "93.184.216.34" if not resolutions else "127.0.0.1"
            resolutions.append(host)
        return original_dns(host, port, *args, **kwargs)

    async def scenario():
        async def serve(reader, writer):
            hits.append(await reader.read(100))
            writer.close()
            await writer.wait_closed()

        server = await asyncio.start_server(serve, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]

        async def connect(host, target_port, **kwargs):
            if target_port == port:
                connections.append(host)
                if host == "93.184.216.34":
                    raise OSError("External networking disabled in this test")
            return await original_connect(host, target_port, **kwargs)

        monkeypatch.setattr(web_network.socket, "getaddrinfo", resolve)
        monkeypatch.setattr(web_proxy.asyncio, "open_connection", connect)
        try:
            async with _client() as (_, reader, writer):
                await _negotiate(reader, writer)
                writer.write(_request("rebound.example", port))
                await writer.drain()
                assert (await asyncio.wait_for(reader.readexactly(10), 2))[1] == 5
        finally:
            server.close()
            await server.wait_closed()
        assert resolutions == ["93.184.216.34"]
        assert connections == ["93.184.216.34"]
        assert hits == []

    asyncio.run(scenario())


def test_proxy_close_releases_incomplete_handshakes_and_listener() -> None:
    async def scenario():
        proxy = PublicWebProxy()
        address = await proxy.start()
        assert await proxy.start() == address
        port = urlsplit(address).port
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        writer.write(b"\x05")
        await writer.drain()
        await asyncio.wait_for(proxy.close(), 2)
        with suppress(ConnectionResetError):
            assert await asyncio.wait_for(reader.read(), 2) == b""
        writer.close()
        with suppress(ConnectionResetError):
            await writer.wait_closed()
        assert not proxy._tasks
        assert not proxy._writers
        with pytest.raises(OSError):
            await asyncio.open_connection("127.0.0.1", port)
        await proxy.close()

    asyncio.run(scenario())


def test_proxy_handshake_timeout_closes_connection(monkeypatch) -> None:
    monkeypatch.setattr(web_proxy, "_CONNECT_TIMEOUT_SECONDS", 0.01)

    async def scenario():
        async with _client() as (_, reader, writer):
            writer.write(b"\x05")
            await writer.drain()
            assert await asyncio.wait_for(reader.read(), 2) == b""

    asyncio.run(scenario())


def test_proxy_close_cancels_pending_outbound_connection(monkeypatch) -> None:
    original_connect = asyncio.open_connection
    monkeypatch.setattr(
        web_proxy, "safe_web_target_addresses", lambda url: ("93.184.216.34",)
    )

    async def scenario():
        connecting = asyncio.Event()
        cancelled = asyncio.Event()

        async def connect(host, port, **kwargs):
            if host == "93.184.216.34":
                connecting.set()
                try:
                    await asyncio.Event().wait()
                finally:
                    cancelled.set()
            return await original_connect(host, port, **kwargs)

        monkeypatch.setattr(web_proxy.asyncio, "open_connection", connect)
        async with _client() as (proxy, reader, writer):
            await _negotiate(reader, writer)
            writer.write(_request("public.example"))
            await writer.drain()
            await asyncio.wait_for(connecting.wait(), 2)
            await asyncio.wait_for(proxy.close(), 2)
            assert cancelled.is_set()
            assert not proxy._tasks
            assert not proxy._writers
            assert await asyncio.wait_for(reader.read(), 2) == b""

    asyncio.run(scenario())


def test_proxy_close_releases_both_ends_of_active_tunnel(monkeypatch) -> None:
    original_connect = asyncio.open_connection
    monkeypatch.setattr(
        web_proxy, "safe_web_target_addresses", lambda url: ("93.184.216.34",)
    )

    async def scenario():
        upstream_closed = asyncio.Event()

        async def serve(reader, writer):
            try:
                await reader.read()
            finally:
                writer.close()
                await writer.wait_closed()
                upstream_closed.set()

        server = await asyncio.start_server(serve, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]

        async def connect(host, target_port, **kwargs):
            if host == "93.184.216.34":
                return await original_connect("127.0.0.1", port)
            return await original_connect(host, target_port, **kwargs)

        monkeypatch.setattr(web_proxy.asyncio, "open_connection", connect)
        try:
            async with _client() as (proxy, reader, writer):
                await _negotiate(reader, writer)
                writer.write(_request("public.example", port))
                await writer.drain()
                assert (await asyncio.wait_for(reader.readexactly(10), 2))[1] == 0
                await asyncio.wait_for(proxy.close(), 2)
                assert await asyncio.wait_for(reader.read(), 2) == b""
                await asyncio.wait_for(upstream_closed.wait(), 2)
                assert not proxy._tasks
                assert not proxy._writers
        finally:
            server.close()
            await server.wait_closed()

    asyncio.run(scenario())
