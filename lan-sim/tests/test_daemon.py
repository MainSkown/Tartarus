"""The daemon end to end: sessions opened and closed through files, served over real sockets.

Loopback addresses stand in for the guest and the fake hosts (Linux binds all of 127/8), and
`reconcile()` is called by hand so no test waits for the poll.
"""

import asyncio
import json
import threading
from dataclasses import replace

import pytest
from support import BannerService, FakeClock, free_port, talk

from lan_session import (
    HostSpec,
    Layout,
    ServiceSpec,
    SessionSpec,
    SessionStatus,
    atomic_write,
    publish_session,
    read_status,
    retract_session,
    wait_for_status,
    write_status,
)
from lan_sim.daemon import Daemon
from lan_sim.limits import Limits
from lan_sim.service import Connection

GUEST_A = "127.0.0.2"
GUEST_B = "127.0.0.4"
HOST_1 = "127.0.0.3"
HOST_2 = "127.0.0.5"
STRANGER = "127.0.0.9"


class HoldService:
    """Says `ready`, then reads until the client goes away."""

    kind = "hold"

    async def serve(self, connection: Connection) -> None:
        await connection.write(b"ready\n")
        while await connection.read(1024):
            pass


class SilentService:
    kind = "silent"

    async def serve(self, connection: Connection) -> None:
        await connection.read(10)


class SleepyService:
    kind = "sleepy"

    async def serve(self, connection: Connection) -> None:
        await asyncio.sleep(3600)


class RaisingService:
    kind = "raising"

    async def serve(self, connection: Connection) -> None:
        raise RuntimeError("password was hunter2")


class SlowService:
    kind = "slow"

    async def serve(self, connection: Connection) -> None:
        connection.clock.advance(2.0)
        await connection.write(b"done\n")


def host(address=HOST_1, kind="banner", port=None, fqdn="fs01.corp.local", extra=()):
    port = port or free_port(address)
    return HostSpec(fqdn, address, "Windows", (("admin", "pw"),), (ServiceSpec(kind, port), *extra))


def session(key="task-1", guest=GUEST_A, hosts=None, preset="small-office"):
    return SessionSpec(key, guest, preset, tuple(hosts or [host()]))


def address_of(spec: SessionSpec, index=0) -> tuple[str, int]:
    first = spec.hosts[index]
    return first.address, first.services[0].port


class World:
    def __init__(self, tmp_path, services=None, **limits):
        self.layout = Layout(tmp_path / "root")
        self.layout.make_directories()
        self.clock = FakeClock()
        every_service = [BannerService(), HoldService(), SilentService(), SleepyService()]
        every_service += [RaisingService(), SlowService()]
        self.services = services or {service.kind: service for service in every_service}
        self.limits = replace(Limits(), **limits)
        self.daemon = Daemon(
            self.layout, self.services, limits=self.limits, clock=self.clock, poll_interval=0.02
        )

    async def open(self, spec: SessionSpec) -> SessionStatus | None:
        publish_session(self.layout, spec)
        await self.daemon.reconcile()
        return read_status(self.layout, spec.key)

    async def close(self, key: str) -> SessionStatus | None:
        retract_session(self.layout, key)
        await self.daemon.reconcile()
        return read_status(self.layout, key)

    def status(self, key: str) -> SessionStatus | None:
        return read_status(self.layout, key)

    def log(self, key: str) -> list[dict]:
        path = self.layout.log_file(key)
        return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []

    def log_of_type(self, key: str, event_type: str) -> list[dict]:
        return [record for record in self.log(key) if record["type"] == event_type]

    def end(self, key: str) -> dict:
        return self.log_of_type(key, "session-end")[-1]

    async def settle(self, key: str, active: int = 0) -> None:
        for _ in range(200):
            if self.daemon.active_connections(key) == active:
                return
            await asyncio.sleep(0.01)
        raise AssertionError("connections did not settle")


def scenario(test):
    """Runs an async test body with a `World` and always shuts the daemon down."""

    def wrapper(tmp_path):
        async def body():
            world = World(tmp_path, **getattr(test, "limits", {}))
            try:
                await test(world)
            finally:
                await world.daemon.shutdown()

        asyncio.run(body())

    wrapper.__name__ = test.__name__
    return wrapper


def with_limits(**limits):
    def decorate(test):
        test.limits = limits
        return test

    return decorate


async def first_line(address: tuple[str, int], source=GUEST_A) -> bytes:
    reader, writer = await asyncio.open_connection(*address, local_addr=(source, 0))
    try:
        return await asyncio.wait_for(reader.readline(), 5)
    finally:
        writer.close()


async def refused(address: tuple[str, int]) -> bool:
    try:
        await asyncio.open_connection(*address, local_addr=(GUEST_A, 0))
    except OSError:
        return True
    return False


# --- the open protocol ----------------------------------------------------------------------------


@scenario
async def test_a_session_is_listening_once_its_listeners_are_bound_and_serves_its_guest(world):
    spec = session()

    status = await world.open(spec)

    assert status == SessionStatus("listening")
    banner = await talk(address_of(spec), source=GUEST_A, send=b"login Administrator\n")
    assert banner == b"hello from fs01.corp.local\nbye\n"
    await world.settle("task-1")
    [login] = world.log_of_type("task-1", "login-attempt")
    assert login["user"] == "Administrator"
    assert login["src"]["ip"] == GUEST_A
    assert login["dst"] == {"ip": HOST_1, "port": address_of(spec)[1]}
    assert login["host"] == "fs01.corp.local"
    assert login["service"] == "banner"
    [connection] = world.log_of_type("task-1", "connection")
    assert connection["bytes_out"] == len(banner)
    assert connection["bytes_in"] == len(b"login Administrator\n")


@scenario
async def test_a_service_that_advances_the_clock_shows_in_the_connection_duration(world):
    spec = session(hosts=[host(kind="slow")])
    await world.open(spec)

    await talk(address_of(spec), source=GUEST_A)
    await world.settle("task-1")

    assert world.log_of_type("task-1", "connection")[0]["duration_ms"] == 2000


@scenario
async def test_no_listener_exists_before_the_session_is_published(world):
    spec = session()

    assert await refused(address_of(spec))
    assert world.status("task-1") is None


@scenario
async def test_a_session_one_of_whose_ports_is_taken_fails_and_binds_nothing(world):
    spec = session(hosts=[host(fqdn="a.corp.local"), host(address=HOST_2, fqdn="b.corp.local")])
    blocker = await asyncio.start_server(
        lambda _reader, writer: writer.close(), *address_of(spec, 1)
    )

    status = await world.open(spec)
    blocker.close()

    assert status.state == "failed"
    assert str(address_of(spec, 1)[1]) in status.error
    assert await refused(address_of(spec, 0))
    assert world.daemon.listening_endpoints() == set()
    assert world.log("task-1") == []


@scenario
async def test_a_host_of_an_unregistered_kind_fails_the_whole_session(world):
    spec = session(hosts=[host(fqdn="a.corp.local"), host(address=HOST_2, kind="smb")])

    status = await world.open(spec)

    assert status.state == "failed"
    assert "no service registered for kind 'smb'" in status.error
    assert world.daemon.listening_endpoints() == set()
    assert await refused(address_of(spec, 0))


@scenario
async def test_a_session_file_that_does_not_validate_fails_with_the_reason(world):
    world.layout.make_directories()
    atomic_write(world.layout.session_file("task-1"), '{"key": "task-1", "bogus": 1}')

    await world.daemon.reconcile()

    status = world.status("task-1")
    assert status.state == "failed"
    assert "bogus" in status.error


@scenario
async def test_a_failed_session_is_not_retried_until_its_file_changes(world):
    atomic_write(world.layout.session_file("task-1"), "not json")
    await world.daemon.reconcile()
    write_status(world.layout, "task-1", SessionStatus("failed", "marker"))

    await world.daemon.reconcile()

    assert world.status("task-1").error == "marker"
    spec = session()
    publish_session(world.layout, spec)
    await world.daemon.reconcile()
    assert world.status("task-1") == SessionStatus("listening")


@scenario
async def test_a_second_session_for_the_same_guest_address_fails_and_the_first_is_untouched(world):
    first, second = session("task-1"), session("task-2", hosts=[host(address=HOST_2)])
    await world.open(first)

    status = await world.open(second)

    assert status.state == "failed"
    assert "guest" in status.error
    assert world.status("task-1") == SessionStatus("listening")
    assert await first_line(address_of(first)) == b"hello from fs01.corp.local\n"


@scenario
async def test_a_session_is_reopened_when_its_file_is_replaced(world):
    spec = session()
    await world.open(spec)
    replacement = session(hosts=[host(address=HOST_2, fqdn="other.corp.local")])

    status = await world.open(replacement)

    assert status == SessionStatus("listening")
    assert await refused(address_of(spec))
    assert await first_line(address_of(replacement)) == b"hello from other.corp.local\n"


# --- the close protocol ---------------------------------------------------------------------------


@scenario
async def test_closing_a_session_unbinds_it_and_ends_the_log_with_the_counters(world):
    spec = session()
    await world.open(spec)
    await talk(address_of(spec), source=GUEST_A)
    await world.settle("task-1")

    status = await world.close("task-1")

    assert status == SessionStatus("closed")
    assert await refused(address_of(spec))
    assert world.end("task-1")["counters"]["connections"] == 1
    assert world.log("task-1")[-1]["type"] == "session-end"
    assert world.daemon.listening_endpoints() == set()


@scenario
async def test_closing_cuts_a_connection_that_is_still_open(world):
    spec = session(hosts=[host(kind="hold")])
    await world.open(spec)
    reader, writer = await asyncio.open_connection(*address_of(spec), local_addr=(GUEST_A, 0))
    assert await reader.readline() == b"ready\n"

    await world.close("task-1")

    assert await asyncio.wait_for(reader.read(), 5) == b""
    writer.close()
    assert world.log_of_type("task-1", "connection")
    assert world.log("task-1")[-1]["type"] == "session-end"


@scenario
async def test_a_failed_session_whose_file_is_removed_is_closed_and_leaves_no_log(world):
    spec = session(hosts=[host(kind="smb")])
    await world.open(spec)

    status = await world.close("task-1")

    assert status == SessionStatus("closed")
    assert world.log("task-1") == []


@scenario
async def test_a_port_can_be_bound_again_at_once_after_a_session_closed(world):
    spec = session()
    await world.open(spec)
    await talk(address_of(spec), source=GUEST_A)
    await world.close("task-1")

    reopened = session("task-2", hosts=[spec.hosts[0]])

    assert await world.open(reopened) == SessionStatus("listening")


@scenario
async def test_the_reopened_log_of_the_same_key_is_appended_not_replaced(world):
    spec = session()
    await world.open(spec)
    await world.close("task-1")
    await world.open(spec)
    await world.close("task-1")

    assert len(world.log_of_type("task-1", "session-end")) == 2


# --- who is served --------------------------------------------------------------------------------


@scenario
async def test_a_connection_from_an_unknown_source_is_closed_and_counted_not_served(world):
    spec = session()
    await world.open(spec)

    assert await first_line(address_of(spec), source=STRANGER) == b""

    assert world.daemon.refused_unknown_source == 1
    assert world.log("task-1") == []
    await world.close("task-1")
    assert world.end("task-1")["counters"]["connections"] == 0


@scenario
async def test_a_guest_cannot_reach_a_host_of_another_session(world):
    first = session("task-1", GUEST_A, [host(HOST_1)])
    second = session("task-2", GUEST_B, [host(HOST_2, fqdn="other.corp.local")])
    await world.open(first)
    await world.open(second)

    wrong = await first_line(address_of(first), source=GUEST_B)
    right = await first_line(address_of(first), source=GUEST_A)

    assert wrong == b""
    assert right == b"hello from fs01.corp.local\n"
    await world.close("task-2")
    assert world.end("task-2")["counters"]["refused"] == {"host-not-in-session": 1}
    assert world.end("task-2")["counters"]["connections"] == 0


@scenario
async def test_a_guest_cannot_use_a_port_its_own_host_does_not_offer(world):
    shared_port = free_port(HOST_1)
    other_port = free_port(HOST_1)
    first = session("task-1", GUEST_A, [host(HOST_1, port=shared_port)])
    second = session("task-2", GUEST_B, [host(HOST_1, port=other_port)])
    await world.open(first)
    await world.open(second)

    assert await first_line((HOST_1, shared_port), source=GUEST_B) == b""

    await world.close("task-2")
    assert world.end("task-2")["counters"]["refused"] == {"port-not-served": 1}


# --- refcounted listeners -------------------------------------------------------------------------


@scenario
async def test_sessions_sharing_a_host_share_its_listener_until_the_last_one_closes(world):
    shared = host(HOST_1)
    first, second = session("task-1", GUEST_A, [shared]), session("task-2", GUEST_B, [shared])
    await world.open(first)
    await world.open(second)
    assert world.daemon.listening_endpoints() == {address_of(first)}

    await world.close("task-1")

    assert await first_line(address_of(first), source=GUEST_B) == b"hello from fs01.corp.local\n"
    assert await first_line(address_of(first), source=GUEST_A) == b""
    await world.close("task-2")
    assert await refused(address_of(first))
    assert world.daemon.listening_endpoints() == set()


@scenario
async def test_a_session_that_fails_to_bind_leaves_a_shared_listener_to_its_other_owner(world):
    shared = host(HOST_1)
    first = session("task-1", GUEST_A, [shared])
    taken = host(HOST_2, fqdn="b.corp.local")
    second = session("task-2", GUEST_B, [shared, taken])
    await world.open(first)
    blocker = await asyncio.start_server(
        lambda _reader, writer: writer.close(), *address_of(second, 1)
    )

    status = await world.open(second)
    blocker.close()

    assert status.state == "failed"
    assert world.daemon.listening_endpoints() == {address_of(first)}
    assert await first_line(address_of(first), source=GUEST_A) == b"hello from fs01.corp.local\n"
    await world.close("task-1")
    assert await refused(address_of(first))


# --- the caps -------------------------------------------------------------------------------------


async def hold(address, source=GUEST_A):
    reader, writer = await asyncio.open_connection(*address, local_addr=(source, 0))
    line = await asyncio.wait_for(reader.readline(), 5)
    return line, reader, writer


@scenario
@with_limits(max_connections_per_source_service=2)
async def test_a_third_connection_from_one_source_to_one_service_is_closed_and_counted(world):
    spec = session(hosts=[host(kind="hold")])
    await world.open(spec)
    first = await hold(address_of(spec))
    second = await hold(address_of(spec))

    third = await hold(address_of(spec))

    assert (first[0], second[0], third[0]) == (b"ready\n", b"ready\n", b"")
    first[2].close()
    await world.settle("task-1", active=1)
    assert (await hold(address_of(spec)))[0] == b"ready\n"
    await world.close("task-1")
    assert world.end("task-1")["counters"]["refused"] == {"connections-per-source-service": 1}
    for _, _, writer in (first, second, third):
        writer.close()


@scenario
@with_limits(max_connections_per_session=2)
async def test_connections_over_the_session_cap_are_closed_whatever_the_service(world):
    extra = ServiceSpec("hold", free_port(HOST_1))
    spec = session(hosts=[host(kind="hold", extra=(extra,))])
    await world.open(spec)
    first = await hold(address_of(spec))
    second = await hold((HOST_1, extra.port))

    third = await hold(address_of(spec))

    assert (first[0], second[0], third[0]) == (b"ready\n", b"ready\n", b"")
    await world.close("task-1")
    assert world.end("task-1")["counters"]["refused"] == {"connections-per-session": 1}


@scenario
@with_limits(max_bytes_read_per_connection=10)
async def test_a_client_that_sends_more_than_the_read_cap_is_cut_off_and_logged(world):
    spec = session(hosts=[host(kind="hold")])
    await world.open(spec)

    reply = await talk(address_of(spec), source=GUEST_A, send=b"x" * 5000)

    assert reply == b"ready\n"
    await world.settle("task-1")
    [request] = world.log_of_type("task-1", "service-request")
    assert request["name"] == "read-cap-exceeded"


@scenario
@with_limits(idle_timeout_seconds=0.2)
async def test_a_silent_client_is_dropped_at_the_idle_timeout(world):
    spec = session(hosts=[host(kind="silent")])
    await world.open(spec)

    reply = await talk(address_of(spec), source=GUEST_A, send=b"")

    assert reply == b""
    await world.settle("task-1")
    assert world.log_of_type("task-1", "service-request")[0]["name"] == "idle-timeout"


@scenario
@with_limits(max_connection_seconds=0.2)
async def test_a_service_that_never_finishes_is_cut_at_the_connection_lifetime(world):
    spec = session(hosts=[host(kind="sleepy")])
    await world.open(spec)

    assert await talk(address_of(spec), source=GUEST_A) == b""

    await world.settle("task-1")
    assert world.log_of_type("task-1", "service-request")[0]["name"] == "connection-too-long"


@scenario
async def test_a_service_that_raises_is_logged_without_its_message_and_the_daemon_carries_on(world):
    spec = session(hosts=[host(kind="raising")])
    await world.open(spec)

    assert await talk(address_of(spec), source=GUEST_A) == b""
    assert await talk(address_of(spec), source=GUEST_A) == b""

    await world.settle("task-1")
    requests = world.log_of_type("task-1", "service-request")
    assert [request["name"] for request in requests] == ["service-error", "service-error"]
    assert requests[0]["detail"] == "RuntimeError"
    assert "hunter2" not in json.dumps(world.log("task-1"))
    assert world.status("task-1") == SessionStatus("listening")


@scenario
@with_limits(full_events_per_service=3, max_events_per_second=1000)
async def test_a_flood_of_connections_logs_a_few_in_full_and_counts_the_rest(world):
    spec = session()
    await world.open(spec)

    for _ in range(30):
        await talk(address_of(spec), source=GUEST_A)
    await world.settle("task-1")
    await world.close("task-1")

    assert len(world.log_of_type("task-1", "connection")) == 3
    assert world.log_of_type("task-1", "aggregate")[0]["count"] == 27
    assert world.end("task-1")["counters"]["connections"] == 30


# --- shutdown and the run loop --------------------------------------------------------------------


@scenario
async def test_shutdown_closes_every_session_flushes_the_log_and_writes_session_end(world):
    first = session("task-1", GUEST_A, [host(HOST_1, kind="hold")])
    second = session("task-2", GUEST_B, [host(HOST_2, fqdn="b.corp.local")])
    await world.open(first)
    await world.open(second)
    reader, writer = await asyncio.open_connection(*address_of(first), local_addr=(GUEST_A, 0))
    await reader.readline()

    await world.daemon.shutdown()

    assert await asyncio.wait_for(reader.read(), 5) == b""
    writer.close()
    for key in ("task-1", "task-2"):
        assert world.status(key) == SessionStatus("closed")
        assert world.log(key)[-1]["type"] == "session-end"
    assert world.log_of_type("task-1", "connection")
    assert await refused(address_of(first))
    assert world.daemon.listening_endpoints() == set()


@scenario
async def test_the_session_files_of_a_stopped_daemon_stay_for_the_control_service(world):
    spec = session()
    await world.open(spec)

    await world.daemon.shutdown()

    assert world.layout.session_file("task-1").exists()


@scenario
async def test_shutdown_twice_is_harmless(world):
    await world.open(session())

    await world.daemon.shutdown()
    await world.daemon.shutdown()

    assert len(world.log_of_type("task-1", "session-end")) == 1


@scenario
async def test_the_registry_is_checked_for_matching_kinds(world):
    with pytest.raises(ValueError, match="kind"):
        Daemon(world.layout, {"smb": BannerService()})


def test_the_run_loop_opens_and_closes_sessions_from_the_directory_and_stops_on_request(tmp_path):
    async def body():
        world = World(tmp_path)
        write_status(world.layout, "stale-1", SessionStatus("listening"))
        spec = session()
        running = asyncio.create_task(world.daemon.run())

        def control_service_opens() -> SessionStatus:
            publish_session(world.layout, spec)
            return wait_for_status(world.layout, "task-1", {"listening", "failed"}, timeout=5)

        opened = await asyncio.to_thread(control_service_opens)
        assert opened == SessionStatus("listening")
        assert await first_line(address_of(spec)) == b"hello from fs01.corp.local\n"

        def control_service_closes() -> SessionStatus:
            retract_session(world.layout, "task-1")
            return wait_for_status(world.layout, "task-1", {"closed"}, timeout=5)

        assert await asyncio.to_thread(control_service_closes) == SessionStatus("closed")
        assert world.status("stale-1") == SessionStatus("closed")
        world.daemon.request_stop()
        await asyncio.wait_for(running, 5)
        assert world.log("task-1")[-1]["type"] == "session-end"

    asyncio.run(body())


def test_stopping_the_run_loop_closes_the_sessions_still_open(tmp_path):
    async def body():
        world = World(tmp_path)
        spec = session()
        publish_session(world.layout, spec)
        running = asyncio.create_task(world.daemon.run())
        for _ in range(200):
            if world.status("task-1"):
                break
            await asyncio.sleep(0.01)

        world.daemon.request_stop()
        await asyncio.wait_for(running, 5)

        assert world.status("task-1") == SessionStatus("closed")
        assert await refused(address_of(spec))

    asyncio.run(body())


def test_no_thread_or_task_is_left_after_a_session_with_connections(tmp_path):
    async def body():
        world = World(tmp_path)
        spec = session()
        await world.open(spec)
        for _ in range(5):
            await talk(address_of(spec), source=GUEST_A)
        await world.close("task-1")
        await world.daemon.shutdown()
        await asyncio.sleep(0)
        others = [task for task in asyncio.all_tasks() if task is not asyncio.current_task()]
        assert others == []

    asyncio.run(body())
    assert threading.active_count() == 1
