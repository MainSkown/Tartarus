"""Hands a framework connection to a library that insists on owning a socket.

The framework's `Connection` is the only way to reach the real peer, so the library gets one end
of a local socket pair and this module carries the bytes through `connection.read` and
`connection.write`. Every byte the client sends is still counted against the read cap and the idle
timeout, and the library never sees the real socket.
"""

import asyncio
import socket
from collections.abc import Awaitable, Callable
from contextlib import suppress

from lan_sim.service import Connection

RELAY_CHUNK_BYTES = 16 * 1024


async def relay_through_socket(
    connection: Connection,
    serve_library: Callable[[socket.socket], Awaitable[None]],
) -> None:
    """Runs `serve_library` on one end of a socket pair and relays `connection` to the other.

    Returns when either side ends. A framework error raised by the client side (read cap, idle
    timeout, peer closed) is raised to the caller, as `Service.serve` would raise it.
    """
    library_end, relay_end = socket.socketpair()
    relay_reader, relay_writer = await asyncio.open_connection(sock=relay_end)
    tasks = {
        asyncio.ensure_future(_forward_from_peer(connection, relay_writer)),
        asyncio.ensure_future(_forward_to_peer(connection, relay_reader)),
        asyncio.ensure_future(serve_library(library_end)),
    }
    try:
        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        for task in done:
            task.result()
    finally:
        relay_writer.close()
        library_end.close()


async def _forward_from_peer(connection: Connection, relay_writer: asyncio.StreamWriter) -> None:
    with suppress(ConnectionError):
        while data := await connection.read(RELAY_CHUNK_BYTES):
            relay_writer.write(data)
            await relay_writer.drain()


async def _forward_to_peer(connection: Connection, relay_reader: asyncio.StreamReader) -> None:
    with suppress(ConnectionError):
        while data := await relay_reader.read(RELAY_CHUNK_BYTES):
            await connection.write(data)
