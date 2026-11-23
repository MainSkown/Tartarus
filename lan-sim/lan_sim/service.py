"""The plug-in boundary: what a protocol implements, and the connection it is handed.

A service never opens a file, touches the network or starts a process. It reads from its
`Connection`, writes to it, and reports what it saw through `connection.log`. The connection
enforces the byte cap and the idle timeout on every read and write, so a service cannot forget to.
"""

import asyncio
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from lan_session import HostSpec, ServiceSpec, SessionSpec
from lan_sim.clock import Clock
from lan_sim.events import Endpoint
from lan_sim.limits import Limits
from lan_sim.session_log import ConnectionLog


class FrameworkError(Exception):
    """Raised by the connection; the dispatcher handles it, a service need not catch it."""

    record_name = "framework-error"


class PeerClosed(FrameworkError):
    record_name = "peer-closed"


class ReadCapExceeded(FrameworkError):
    record_name = "read-cap-exceeded"


class IdleTimeout(FrameworkError):
    record_name = "idle-timeout"


class Service(Protocol):
    """One protocol on one port. `kind` is the name a preset's service entry uses."""

    kind: str

    async def serve(self, connection: "Connection") -> None:
        """Speaks the protocol on `connection` until it is done; exceptions end the connection."""
        ...


@runtime_checkable
class SessionAwareService(Service, Protocol):
    """A service that keeps state per session and wants to hear when a session is closed."""

    async def session_closed(self, session_key: str) -> None:
        """Called once after the session's connections have ended, before `closed` is written."""
        ...


@dataclass(eq=False)
class Connection:
    reader: asyncio.StreamReader
    writer: asyncio.StreamWriter
    host: HostSpec
    service: ServiceSpec
    session: SessionSpec
    source: Endpoint
    destination: Endpoint
    log: ConnectionLog
    clock: Clock
    limits: Limits
    bytes_in: int = 0
    bytes_out: int = 0
    _read_budget: int = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._read_budget = self.limits.max_bytes_read_per_connection

    def __setattr__(self, name: str, value: Any) -> None:
        if name == "limits" and "limits" in self.__dict__:
            raise AttributeError("a connection's limits are the daemon's; use raise_read_budget")
        super().__setattr__(name, value)

    def raise_read_budget(self, total_bytes: int) -> None:
        """Raises this connection's total read budget; never lowers it, never passes the ceiling.

        The only way a service changes what its connection may do: a service that has authenticated
        its peer may need more than the pre-authentication default (SMB file writes).
        """
        ceiling = self.limits.max_raised_read_budget_per_connection
        if total_bytes > ceiling:
            raise ValueError(f"{total_bytes} bytes is over the ceiling of {ceiling}")
        self._read_budget = max(self._read_budget, total_bytes)

    async def read(self, size: int) -> bytes:
        """Up to `size` bytes, or `b""` at the end of the stream; counts against the read cap."""
        if size <= 0:
            raise ValueError("size must be positive")
        size = min(size, self._remaining_read_budget())
        data = await self._guarded(self.reader.read(size))
        self.bytes_in += len(data)
        return data

    async def read_exactly(self, size: int) -> bytes:
        if size <= 0:
            raise ValueError("size must be positive")
        if size > self._remaining_read_budget():
            raise ReadCapExceeded(f"{size} bytes asked, over the connection's read cap")
        try:
            data = await self._guarded(self.reader.readexactly(size))
        except asyncio.IncompleteReadError as error:
            self.bytes_in += len(error.partial)
            raise PeerClosed("the peer closed before the bytes arrived") from error
        self.bytes_in += len(data)
        return data

    async def read_until(self, separator: bytes, max_bytes: int) -> bytes:
        """Up to and including `separator`; over the cap if it is not within `max_bytes`."""
        budget = self._remaining_read_budget()
        try:
            data = await self._guarded(self.reader.readuntil(separator))
        except asyncio.IncompleteReadError as error:
            self.bytes_in += len(error.partial)
            raise PeerClosed("the peer closed before the separator arrived") from error
        except asyncio.LimitOverrunError as error:
            raise ReadCapExceeded("no separator within the connection's read cap") from error
        self.bytes_in += len(data)
        if len(data) > min(max_bytes, budget):
            raise ReadCapExceeded(f"{len(data)} bytes before the separator, over the cap")
        return data

    async def write(self, data: bytes) -> None:
        if self.writer.is_closing():
            raise PeerClosed("the connection is closing")
        self.writer.write(data)
        await self._guarded(self.writer.drain())
        self.bytes_out += len(data)

    def _remaining_read_budget(self) -> int:
        remaining = self._read_budget - self.bytes_in
        if remaining <= 0:
            raise ReadCapExceeded(f"more than {self._read_budget} bytes read on one connection")
        return remaining

    async def _guarded(self, awaitable: Any) -> Any:
        try:
            async with asyncio.timeout(self.limits.idle_timeout_seconds):
                return await awaitable
        except TimeoutError as error:
            raise IdleTimeout(
                f"no traffic for {self.limits.idle_timeout_seconds:g} seconds"
            ) from error
        except ConnectionError as error:
            raise PeerClosed("the connection was reset") from error
