"""Tests of `bin/machine-broker`, the server around `machine_broker_logic`, on a real UNIX socket.

What the broker does for a request is tested in test_machine_broker_logic.py; this is the socket:
who can connect, how many at once, that it serves requests side by side, and how it stops.
"""

import importlib
import json
import os
import socket
import stat
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from functools import partial

import pytest
from test_control_http import BIN, load_script  # noqa: F401 - importing it puts bin/ on sys.path

machine_broker = load_script("machine-broker")
logic = importlib.import_module("machine_broker_logic")
client = importlib.import_module("machine_broker_client")


class Machines:
    def __init__(self):
        self.performed: list[tuple[str, str]] = []
        self.gate: threading.Event | None = None
        self.arrived = threading.Semaphore(0)

    def perform(self, request, connected):
        self.arrived.release()
        if self.gate:
            self.gate.wait(5)
        self.performed.append((request.operation, request.label))


@pytest.fixture
def socket_path(tmp_path_factory):
    return tmp_path_factory.mktemp("run") / "machine-broker.sock"


@contextmanager
def running(socket_path, machines, *, allowed=None, capacity=8) -> Iterator[threading.Event]:
    listener = machine_broker.listen(socket_path, os.getgid())
    stop = threading.Event()
    logged: list[str] = []
    handle = partial(
        logic.serve_connection,
        machines=machines,
        allowed_uids=allowed if allowed is not None else {os.getuid()},
        log=logged.append,
    )
    server = threading.Thread(
        target=machine_broker.serve,
        args=(listener, handle),
        kwargs={"stop": stop, "capacity": capacity},
    )
    server.start()
    try:
        yield stop
    finally:
        stop.set()
        server.join(5)
        listener.close()


def test_the_socket_is_open_to_its_owner_and_group_only(socket_path):
    listener = machine_broker.listen(socket_path, os.getgid())

    mode = stat.S_IMODE(socket_path.stat().st_mode)
    listener.close()

    assert mode == 0o660
    assert socket_path.stat().st_gid == os.getgid()


def test_a_socket_left_by_an_earlier_run_is_replaced(socket_path):
    machine_broker.listen(socket_path, os.getgid()).close()

    machine_broker.listen(socket_path, os.getgid()).close()


def test_a_request_over_the_socket_is_performed_through_the_real_client(socket_path):
    machines = Machines()

    with running(socket_path, machines):
        client.ask(client.STOP, "win", socket_path=str(socket_path), timeout=3)

    assert machines.performed == [("stop", "win")]


def test_a_refusal_reaches_the_client_as_an_error(socket_path):
    class Refusing:
        def perform(self, request, connected):
            raise logic.Refusal("win is not a registered guest")

    with (
        running(socket_path, Refusing()),
        pytest.raises(client.MachineBrokerError, match="not a registered guest"),
    ):
        client.ask(client.REVERT, "win", socket_path=str(socket_path), timeout=3)


def test_a_user_who_is_not_allowed_gets_an_error_and_nothing_is_performed(socket_path):
    machines = Machines()

    with (
        running(socket_path, machines, allowed={os.getuid() + 1}),
        pytest.raises(client.MachineBrokerError, match="may not use"),
    ):
        client.ask(client.STOP, "win", socket_path=str(socket_path), timeout=3)

    assert machines.performed == []


def test_requests_for_different_guests_are_served_at_the_same_time(socket_path):
    machines = Machines()
    machines.gate = threading.Event()
    errors: list[BaseException] = []

    def ask(label):
        try:
            client.ask(client.STOP, label, socket_path=str(socket_path), timeout=5)
        except BaseException as error:  # noqa: BLE001 - reported to the test thread
            errors.append(error)

    with running(socket_path, machines):
        threads = [threading.Thread(target=ask, args=(label,)) for label in ("win", "lab-1")]
        for thread in threads:
            thread.start()
        both_arrived = machines.arrived.acquire(timeout=3) and machines.arrived.acquire(timeout=3)
        machines.gate.set()
        for thread in threads:
            thread.join(5)

    assert both_arrived
    assert errors == []


def test_a_slow_client_does_not_keep_another_waiting(socket_path):
    machines = Machines()
    idle = socket.socket(socket.AF_UNIX)

    with running(socket_path, machines):
        idle.connect(str(socket_path))
        client.ask(client.STOP, "win", socket_path=str(socket_path), timeout=3)
        idle.close()

    assert machines.performed == [("stop", "win")]


def test_a_flood_beyond_the_capacity_is_turned_away_not_queued(socket_path):
    machines = Machines()
    machines.gate = threading.Event()
    holders = [
        threading.Thread(
            target=lambda: client.ask(client.STOP, "win", socket_path=str(socket_path), timeout=5)
        )
        for _ in range(2)
    ]

    with running(socket_path, machines, capacity=2):
        for holder in holders:
            holder.start()
        assert machines.arrived.acquire(timeout=3)
        assert machines.arrived.acquire(timeout=3)
        with pytest.raises(client.MachineBrokerError, match="busy"):
            client.ask(client.STOP, "lab-1", socket_path=str(socket_path), timeout=3)
        machines.gate.set()
        for holder in holders:
            holder.join(5)


def test_stopping_closes_the_socket_and_removes_its_file(socket_path):
    machines = Machines()
    with running(socket_path, machines) as stop:
        stop.set()
        deadline = time.monotonic() + 3
        while socket_path.exists() and time.monotonic() < deadline:
            time.sleep(0.05)

    assert not socket_path.exists()


def test_a_stop_waits_for_the_request_in_progress(socket_path):
    machines = Machines()
    machines.gate = threading.Event()
    outcome: list[str] = []

    def ask():
        client.ask(client.STOP, "win", socket_path=str(socket_path), timeout=5)
        outcome.append("answered")

    with running(socket_path, machines) as stop:
        asking = threading.Thread(target=ask)
        asking.start()
        assert machines.arrived.acquire(timeout=3)
        stop.set()
        threading.Timer(0.3, machines.gate.set).start()
        asking.join(5)

    assert outcome == ["answered"]


def test_the_staging_folder_is_prepared_before_the_socket_is_opened(tmp_path, monkeypatch):
    prepared: list[str] = []

    class Machines:
        def prepare_staging(self):
            prepared.append("staging")

    class OpenedError(Exception):
        pass

    def listen(*_arguments):
        raise OpenedError(list(prepared))

    monkeypatch.setattr(machine_broker, "listen", listen)
    container = machine_broker.Container(
        socket_path=tmp_path / "s.sock",
        machines=Machines(),
        allowed_uids={0},
        group=0,
        log=lambda _m: None,
    )

    with pytest.raises(OpenedError) as opened:
        machine_broker.main(container, threading.Event())

    assert opened.value.args == (["staging"],)


def test_the_users_allowed_are_root_and_cape():
    users = {"cape": (999, 995)}

    allowed, group = machine_broker.cape_and_root(lambda name: users[name])

    assert allowed == {0, 999}
    assert group == 995


def test_a_missing_cape_user_stops_the_broker_with_a_message():
    def nobody(_name):
        raise KeyError("cape")

    with pytest.raises(SystemExit, match="cape"):
        machine_broker.cape_and_root(nobody)


def test_the_request_json_the_client_builds_is_what_the_server_parses():
    request = logic.parse_request(client.encode_request("dump", "win", 12))

    assert json.loads(client.encode_request("dump", "win", 12)) == {
        "op": "dump",
        "label": "win",
        "task_id": 12,
    }
    assert (request.operation, request.label, request.task_id) == ("dump", "win", 12)
