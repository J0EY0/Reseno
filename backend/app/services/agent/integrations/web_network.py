import asyncio
import ipaddress
import socket
from urllib.parse import urlsplit

import httpx

TUN_FAKE_IP_NETWORK = ipaddress.ip_network("198.18.0.0/15")
BLOCKED_WEB_HOSTS = frozenset(
    {
        "instance-data.ec2.internal",
        "metadata.azure.internal",
        "metadata.google",
        "metadata.google.internal",
    }
)


def _effective_address(value: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address:
    address = ipaddress.ip_address(value)
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
        return address.ipv4_mapped
    return address


def is_public_web_url(url: str) -> bool:
    """Accept HTTP(S) URLs without credentials or private literal addresses."""

    try:
        parsed = urlsplit(url)
        hostname = (parsed.hostname or "").rstrip(".").casefold()
        _ = parsed.port
    except ValueError:
        return False
    if (
        parsed.scheme not in {"http", "https"}
        or not hostname
        or "%" in hostname
        or parsed.username is not None
        or parsed.password is not None
        or hostname == "localhost"
        or hostname.endswith(".localhost")
        or hostname in BLOCKED_WEB_HOSTS
    ):
        return False
    try:
        address = _effective_address(hostname)
    except ValueError:
        return True
    return address.is_global and not address.is_multicast


def safe_web_target_addresses(url: str) -> tuple[str, ...] | None:
    """Resolve all target addresses in connection order and reject private DNS."""

    if not is_public_web_url(url):
        return None
    parsed = urlsplit(url)
    hostname = (parsed.hostname or "").rstrip(".")
    try:
        address = _effective_address(hostname)
    except ValueError:
        try:
            records = socket.getaddrinfo(
                hostname,
                parsed.port or (443 if parsed.scheme == "https" else 80),
                type=socket.SOCK_STREAM,
            )
            addresses = tuple(dict.fromkeys(str(record[4][0]) for record in records))
            for value in addresses:
                resolved = _effective_address(value)
                if resolved.is_multicast or not (
                    resolved.is_global
                    or (resolved.version == 4 and resolved in TUN_FAKE_IP_NETWORK)
                ):
                    return None
        except (OSError, UnicodeError, ValueError):
            return None
        return addresses or None
    return (str(address),)


class PublicWebTransport(httpx.AsyncBaseTransport):
    """Connect to validated IPs while retaining HTTP and TLS origin identity."""

    def __init__(self) -> None:
        self._transports: dict[
            tuple[str, bytes, int | None], httpx.AsyncHTTPTransport
        ] = {}

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        addresses = await asyncio.to_thread(safe_web_target_addresses, str(request.url))
        if not addresses:
            raise httpx.ConnectError("The web target is not public.", request=request)

        origin = (request.url.scheme, request.url.raw_host, request.url.port)
        transport = self._transports.get(origin)
        if transport is None:
            transport = httpx.AsyncHTTPTransport(trust_env=False)
            self._transports[origin] = transport
        headers = request.headers.copy()
        headers["Host"] = request.url.netloc.decode("ascii")
        extensions = {
            **request.extensions,
            "sni_hostname": request.url.raw_host.decode(),
        }
        for index, address in enumerate(addresses):
            pinned = httpx.Request(
                request.method,
                request.url.copy_with(host=address),
                headers=headers,
                stream=request.stream,
                extensions=extensions,
            )
            try:
                response = await transport.handle_async_request(pinned)
            except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
                if index + 1 == len(addresses):
                    raise httpx.ConnectError(
                        "Unable to connect to the public web target.", request=request
                    ) from exc
            else:
                response.request = request
                return response
        raise AssertionError("A validated target must have an address.")

    async def aclose(self) -> None:
        transports, self._transports = self._transports, {}
        await asyncio.gather(*(transport.aclose() for transport in transports.values()))
