"""The SSH service against clients that do not speak SSH: each must end in bounded time.

The daemon must still serve the next honest client afterwards.
"""

import asyncio
from contextlib import suppress

from test_daemon import GUEST_A, World
from test_service_ssh import KEY, close, login, open_session, run, ssh_host

from lan_sim.services import ssh

ENDS_WITHIN_SECONDS = 10
MEGABYTE = 1024 * 1024


async def connect_raw(address, port):
    return await asyncio.open_connection(address, port, local_addr=(GUEST_A, 0))


async def read_to_end(reader: asyncio.StreamReader) -> bytes:
    received = b""
    while chunk := await reader.read(65536):
        received += chunk
    return received


async def exchange_until_closed(address, port, sender) -> bytes:
    """Runs `sender(writer)` alongside reading; returns what the server sent before it closed."""
    reader, writer = await connect_raw(address, port)
    send = asyncio.ensure_future(sender(writer))
    try:
        return await asyncio.wait_for(read_to_end(reader), ENDS_WITHIN_SECONDS)
    except ConnectionError:
        return b""
    finally:
        send.cancel()
        with suppress(asyncio.CancelledError, ConnectionError):
            await send
        writer.close()


def sends(payload: bytes, chunk_size: int = 65536):
    async def sender(writer: asyncio.StreamWriter) -> None:
        for offset in range(0, len(payload), chunk_size):
            writer.write(payload[offset : offset + chunk_size])
            await writer.drain()

    return sender


def test_garbage_instead_of_a_banner_ends_the_connection_and_the_daemon_stays_up(tmp_path):
    async def body(world: World):
        [(address, port)] = await open_session(world, ssh_host())
        await exchange_until_closed(address, port, sends(b"GET / HTTP/1.1\r\nHost: x\r\n\r\n"))

        connection = await login(address, port, password="after-garbage")
        await close(connection)
        await world.settle(KEY)
        [attempt] = world.log_of_type(KEY, "login-attempt")
        assert attempt["secret"] == "after-garbage"

    run(tmp_path, body)


def test_a_ten_megabyte_banner_line_ends_the_connection(tmp_path):
    async def body(world: World):
        [(address, port)] = await open_session(world, ssh_host())
        payload = b"A" * (10 * 1024 * 1024) + b"\r\n"
        await exchange_until_closed(address, port, sends(payload))

        await world.settle(KEY)
        assert world.log_of_type(KEY, "login-attempt") == []
        [cut] = world.log_of_type(KEY, "service-request")
        assert cut["name"] == "read-cap-exceeded"
        connection = await login(address, port, password="after-flood")
        await close(connection)

    run(tmp_path, body)


def test_a_slow_drip_handshake_is_cut_within_the_login_window(tmp_path, monkeypatch):
    monkeypatch.setattr(ssh, "LOGIN_TIMEOUT_SECONDS", 1.0)

    async def drip(writer: asyncio.StreamWriter) -> None:
        for character in b"SSH-2.0-slow-client\r\n":
            writer.write(bytes([character]))
            await writer.drain()
            await asyncio.sleep(0.2)

    async def body(world: World):
        [(address, port)] = await open_session(world, ssh_host())
        loop = asyncio.get_running_loop()
        started = loop.time()
        await exchange_until_closed(address, port, drip)
        assert loop.time() - started < ENDS_WITHIN_SECONDS

        connection = await login(address, port, password="after-drip")
        await close(connection)

    run(tmp_path, body)
