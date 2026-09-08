from __future__ import annotations

import asyncio
import ipaddress
import re

from .web_network import safe_web_target_addresses

_DOMAIN_LABEL = re.compile(r"[A-Za-z0-9_](?:[A-Za-z0-9_-]{0,61}[A-Za-z0-9_])?")
_CONNECT_TIMEOUT_SECONDS = 10.0


class _SocksRequestError(Exception):
    def __init__(self, reply: int) -> None:
        self.reply = reply


async def _read_target(reader: asyncio.StreamReader) -> tuple[str, int]:
    version, command, reserved, address_type = await reader.readexactly(4)
    if version != 5 or reserved != 0:
        raise _SocksRequestError(1)
    if command != 1:
        raise _SocksRequestError(7)
    if address_type == 1:
        hostname = str(ipaddress.IPv4Address(await reader.readexactly(4)))
    elif address_type == 4:
        hostname = str(ipaddress.IPv6Address(await reader.readexactly(16)))
    elif address_type == 3:
        length = (await reader.readexactly(1))[0]
        if not 0 < length <= 253:
            raise _SocksRequestError(8)
        try:
            hostname = (await reader.readexactly(length)).decode("ascii")
        except UnicodeDecodeError as exc:
            raise _SocksRequestError(8) from exc
        if any(
            _DOMAIN_LABEL.fullmatch(label) is None
            for label in hostname.removesuffix(".").split(".")
        ):
            raise _SocksRequestError(8)
    else:
        raise _SocksRequestError(8)
    port = int.from_bytes(await reader.readexactly(2), "big")
    if port == 0:
        raise _SocksRequestError(1)
    return hostname, port


async def _reply(writer: asyncio.StreamWriter, status: int) -> None:
    writer.write(bytes((5, status, 0, 1, 0, 0, 0, 0, 0, 0)))
    await writer.drain()


async def _copy_stream(
    reader: asyncio.StreamReader, writer: asyncio.StreamWriter
) -> None:
    while data := await reader.read(65_536):
        writer.write(data)
        await writer.drain()
    if writer.can_write_eof():
        writer.write_eof()
        await writer.drain()


class PublicWebProxy:
    """A loopback SOCKS5 CONNECT proxy restricted to public web destinations."""

    def __init__(self) -> None:
        self._server: asyncio.Server | None = None
        self._lock = asyncio.Lock()
        self._closing = False
        self._tasks: set[asyncio.Task[None]] = set()
        self._writers: set[asyncio.StreamWriter] = set()

    async def start(self) -> str:
        async with self._lock:
            if self._server is None:
                self._closing = False
                self._server = await asyncio.start_server(self._accept, "127.0.0.1", 0)
            port = self._server.sockets[0].getsockname()[1]
            return f"socks5://127.0.0.1:{port}"

    async def close(self) -> None:
        async with self._lock:
            self._closing = True
            server, self._server = self._server, None
            if server is not None:
                server.close()
            for writer in tuple(self._writers):
                writer.close()
            while self._tasks:
                tasks = tuple(self._tasks)
                for task in tasks:
                    task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
                self._tasks.difference_update(tasks)
            writers = tuple(self._writers)
            for writer in writers:
                writer.close()
            await asyncio.gather(
                *(writer.wait_closed() for writer in writers), return_exceptions=True
            )
            self._writers.difference_update(writers)
            if server is not None:
                await server.wait_closed()

    def _accept(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        self._writers.add(writer)
        task = asyncio.create_task(self._handle(reader, writer))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _handle(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        upstream_writer: asyncio.StreamWriter | None = None
        try:
            if self._closing:
                return
            async with asyncio.timeout(_CONNECT_TIMEOUT_SECONDS):
                version, method_count = await reader.readexactly(2)
                if version != 5 or method_count == 0:
                    return
                methods = await reader.readexactly(method_count)
                writer.write(b"\x05\x00" if 0 in methods else b"\x05\xff")
                await writer.drain()
                if 0 not in methods:
                    return
                hostname, port = await _read_target(reader)
                authority = f"[{hostname}]" if ":" in hostname else hostname
                addresses = await asyncio.to_thread(
                    safe_web_target_addresses, f"http://{authority}:{port}"
                )
                if not addresses:
                    await _reply(writer, 2)
                    return
                for address in addresses:
                    try:
                        (
                            upstream_reader,
                            upstream_writer,
                        ) = await asyncio.open_connection(address, port)
                        self._writers.add(upstream_writer)
                        break
                    except OSError:
                        continue
                else:
                    await _reply(writer, 5)
                    return
                await _reply(writer, 0)
            tasks = (
                asyncio.create_task(_copy_stream(reader, upstream_writer)),
                asyncio.create_task(_copy_stream(upstream_reader, writer)),
            )
            try:
                await asyncio.gather(*tasks)
            finally:
                for task in tasks:
                    task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
        except _SocksRequestError as exc:
            try:
                await _reply(writer, exc.reply)
            except OSError:
                pass
        except (OSError, asyncio.IncompleteReadError, TimeoutError):
            pass
        finally:
            writers = [writer]
            if upstream_writer is not None:
                writers.append(upstream_writer)
            for stream in writers:
                stream.close()
                self._writers.discard(stream)
            await asyncio.gather(
                *(stream.wait_closed() for stream in writers), return_exceptions=True
            )
