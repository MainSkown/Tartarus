"""The connection a service sees: reads and writes that enforce the caps for it."""

import asyncio
from dataclasses import replace

import pytest
from support import FakeClock, ListSink

from lan_session import HostSpec, ServiceSpec, SessionSpec
from lan_sim.events import Endpoint
from lan_sim.limits import Limits
from lan_sim.service import (
    Connection,
    IdleTimeout,
    PeerClosed,
    ReadCapExceeded,
)
from lan_sim.session_log import SessionLog

HOST = HostSpec(
    "fs01.corp.local", "192.168.150.201", "Windows", (("a", "b"),), (ServiceSpec("banner", 4000),)
)
SESSION = SessionSpec("task-1", "192.168.150.10", "small-office", (HOST,))
SRC = Endpoint("192.168.150.10", 50000)
DST = Endpoint("192.168.150.201", 4000)


class FakeWriter:
    def __init__(self, *, drain_hangs=False, drain_error=None):
        self.written = b""
        self.closing = False
        self.drain_hangs = drain_hangs
        self.drain_error = drain_error

    def write(self, data):
        self.written += data

    async def drain(self):
        if self.drain_error:
            raise self.drain_error
        if self.drain_hangs:
            await asyncio.sleep(3600)

    def is_closing(self):
        return self.closing

    def close(self):
        self.closing = True

    def get_extra_info(self, name):
        return None


def make(reader_data=b"", *, eof=True, writer=None, **limits):
    reader = asyncio.StreamReader()
    reader.feed_data(reader_data)
    if eof:
        reader.feed_eof()
    clock = FakeClock()
    limit_values = replace(Limits(), idle_timeout_seconds=0.05, **limits)
    log = SessionLog("task-1", ListSink(), clock, limit_values)
    return Connection(
        reader=reader,
        writer=writer or FakeWriter(),
        host=HOST,
        service=HOST.services[0],
        session=SESSION,
        source=SRC,
        destination=DST,
        log=log.connection_log(HOST.fqdn, "banner", SRC, DST),
        clock=clock,
        limits=limit_values,
    )


def run(coroutine):
    return asyncio.run(coroutine)


def test_the_connection_carries_what_a_service_needs_to_know():
    async def scenario():
        return make()

    connection = run(scenario())

    assert connection.host is HOST
    assert connection.session is SESSION
    assert connection.source == ("192.168.150.10", 50000)
    assert connection.destination == ("192.168.150.201", 4000)
    assert connection.clock.monotonic() == 1000.0


def test_read_returns_what_arrived_and_counts_it():
    async def scenario():
        connection = make(b"hello")
        data = await connection.read(100)
        return data, connection.bytes_in

    assert run(scenario()) == (b"hello", 5)


def test_read_returns_empty_bytes_at_the_end_of_the_stream():
    async def scenario():
        connection = make(b"")
        return await connection.read(10)

    assert run(scenario()) == b""


def test_read_never_returns_more_than_asked():
    async def scenario():
        connection = make(b"abcdef")
        return await connection.read(2), await connection.read(10)

    assert run(scenario()) == (b"ab", b"cdef")


def test_the_total_read_cap_ends_in_an_error_not_a_silent_cut():
    async def scenario():
        connection = make(b"x" * 100, max_bytes_read_per_connection=10)
        first = await connection.read(8)
        second = await connection.read(8)
        with pytest.raises(ReadCapExceeded):
            await connection.read(8)
        return len(first), len(second), connection.bytes_in

    assert run(scenario()) == (8, 2, 10)


def test_read_exactly_that_would_pass_the_cap_fails_before_reading():
    async def scenario():
        connection = make(b"x" * 100, max_bytes_read_per_connection=10)
        with pytest.raises(ReadCapExceeded):
            await connection.read_exactly(11)
        return connection.bytes_in

    assert run(scenario()) == 0


def test_a_service_can_raise_its_read_budget_up_to_the_ceiling():
    async def scenario():
        connection = make(b"x" * 100, max_bytes_read_per_connection=10)
        connection.raise_read_budget(50)
        data = await connection.read(100)
        with pytest.raises(ReadCapExceeded):
            await connection.read_exactly(51)
        return len(data), connection.limits.max_bytes_read_per_connection

    assert run(scenario()) == (50, 10)


def test_raising_the_read_budget_never_lowers_it():
    async def scenario():
        connection = make(b"x" * 100, max_bytes_read_per_connection=10)
        connection.raise_read_budget(5)
        connection.raise_read_budget(8)
        return len(await connection.read(100))

    assert run(scenario()) == 10


def test_the_read_budget_cannot_be_raised_past_the_ceiling():
    async def scenario():
        connection = make(b"", max_raised_read_budget_per_connection=1000)
        connection.raise_read_budget(1000)
        with pytest.raises(ValueError, match="ceiling"):
            connection.raise_read_budget(1001)

    run(scenario())


def test_the_default_ceiling_is_64_mib():
    assert Limits().max_raised_read_budget_per_connection == 64 * 1024 * 1024


def test_a_service_cannot_replace_the_connections_limits():
    async def scenario():
        connection = make(b"")
        with pytest.raises(AttributeError):
            connection.limits = replace(connection.limits, max_bytes_read_per_connection=10**9)

    run(scenario())


def test_read_exactly_returns_the_bytes_and_counts_them():
    async def scenario():
        connection = make(b"abcdef")
        return await connection.read_exactly(4), connection.bytes_in

    assert run(scenario()) == (b"abcd", 4)


def test_read_exactly_on_a_stream_that_ends_early_is_a_closed_peer():
    async def scenario():
        connection = make(b"abc")
        with pytest.raises(PeerClosed):
            await connection.read_exactly(10)

    run(scenario())


def test_read_until_returns_through_the_separator():
    async def scenario():
        connection = make(b"USER admin\r\nrest")
        return await connection.read_until(b"\r\n", 100), connection.bytes_in

    assert run(scenario()) == (b"USER admin\r\n", 12)


def test_read_until_without_a_separator_in_range_is_over_the_cap():
    async def scenario():
        connection = make(b"x" * 500 + b"\n")
        with pytest.raises(ReadCapExceeded):
            await connection.read_until(b"\n", 100)

    run(scenario())


def test_read_until_beyond_the_connection_cap_is_over_the_cap():
    async def scenario():
        connection = make(b"x" * 50 + b"\n", max_bytes_read_per_connection=20)
        with pytest.raises(ReadCapExceeded):
            await connection.read_until(b"\n", 1000)

    run(scenario())


def test_read_until_on_a_stream_that_ends_first_is_a_closed_peer():
    async def scenario():
        connection = make(b"no newline here")
        with pytest.raises(PeerClosed):
            await connection.read_until(b"\n", 100)

    run(scenario())


def test_a_silent_peer_hits_the_idle_timeout():
    async def scenario():
        connection = make(b"", eof=False)
        with pytest.raises(IdleTimeout):
            await connection.read(10)

    run(scenario())


def test_a_peer_that_never_reads_hits_the_idle_timeout_on_write():
    async def scenario():
        connection = make(writer=FakeWriter(drain_hangs=True))
        with pytest.raises(IdleTimeout):
            await connection.write(b"data")

    run(scenario())


def test_a_reset_connection_is_a_closed_peer_for_reads_and_writes():
    class Resetting(asyncio.StreamReader):
        async def read(self, n=-1):
            raise ConnectionResetError

    async def scenario():
        connection = make(writer=FakeWriter(drain_error=BrokenPipeError()))
        connection.reader = Resetting()
        with pytest.raises(PeerClosed):
            await connection.read(1)
        with pytest.raises(PeerClosed):
            await connection.write(b"x")

    run(scenario())


def test_write_counts_the_bytes_and_refuses_on_a_closing_writer():
    async def scenario():
        writer = FakeWriter()
        connection = make(writer=writer)
        await connection.write(b"hello")
        writer.closing = True
        with pytest.raises(PeerClosed):
            await connection.write(b"more")
        return writer.written, connection.bytes_out

    assert run(scenario()) == (b"hello", 5)


def test_a_read_of_nothing_is_a_programming_error():
    async def scenario():
        connection = make(b"x")
        with pytest.raises(ValueError, match="positive"):
            await connection.read(0)

    run(scenario())
