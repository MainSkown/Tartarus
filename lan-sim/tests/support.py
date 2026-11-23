"""Helpers shared by the lan-sim tests: a manual clock, a list sink and a few stand-in services."""

import asyncio
import socket
from contextlib import suppress
from datetime import UTC, datetime, timedelta

from lan_sim.service import Connection

START = datetime(2026, 11, 23, 12, 0, 0, tzinfo=UTC)


class FakeClock:
    def __init__(self) -> None:
        self.seconds = 0.0

    def now(self) -> datetime:
        return START + timedelta(seconds=self.seconds)

    def monotonic(self) -> float:
        return 1000.0 + self.seconds

    def advance(self, seconds: float) -> None:
        self.seconds += seconds


class ListSink:
    def __init__(self) -> None:
        self.lines: list[str] = []
        self.closed = False

    def write_line(self, line: str) -> None:
        self.lines.append(line)

    def close(self) -> None:
        self.closed = True


class BannerService:
    """Test-only: greets with a line, then logs a login for every `login <user>` line it is sent."""

    kind = "banner"

    async def serve(self, connection: Connection) -> None:
        await connection.write(f"hello from {connection.host.fqdn}\n".encode())
        line = await connection.read_until(b"\n", 256)
        verb, _, user = line.decode("utf-8", "surrogateescape").strip().partition(" ")
        if verb == "login":
            connection.log.login_attempt(
                user=user, domain="CORP", mechanism="password", secret="hunter2", success=False
            )
        await connection.write(b"bye\n")


def free_port(address: str) -> int:
    with socket.socket() as probe:
        probe.bind((address, 0))
        return probe.getsockname()[1]


async def talk(destination: tuple[str, int], *, source: str, send: bytes = b"\n") -> bytes:
    """Connects from `source`, sends `send` and returns what the server wrote until it closed."""
    reader, writer = await asyncio.open_connection(*destination, local_addr=(source, 0))
    received = b""
    try:
        if send:
            writer.write(send)
            with suppress(ConnectionError):
                await writer.drain()
        while chunk := await asyncio.wait_for(reader.read(4096), 5):
            received += chunk
    except ConnectionError:
        pass
    finally:
        writer.close()
    return received
