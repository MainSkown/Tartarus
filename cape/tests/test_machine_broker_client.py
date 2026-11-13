"""The machine broker's wire protocol and the client CAPE's patched machinery calls it with.

The client is stdlib only and ships into CAPE's tree, so it is tested against a stand-in broker on a
real UNIX socket, which is also how its timeouts and its single attempt are checked.
"""

import importlib
import json
import socket
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import suppress

import pytest
from test_control_http import BIN  # noqa: F401 - importing it puts bin/ on sys.path

client = importlib.import_module("machine_broker_client")

ANALYSES = "/opt/CAPEv2/storage/analyses"


def dump_path_of(task_id: int) -> str:
    return f"{ANALYSES}/{task_id}/memory.dmp"


class StandInBroker:
    def __init__(self, listener: socket.socket, behaviour: Callable[[socket.socket], None]):
        self.listener = listener
        self.behaviour = behaviour
        self.received: list[bytes] = []
        self.connections = 0

    def run(self) -> None:
        while True:
            try:
                connection, _ = self.listener.accept()
            except OSError:
                return
            self.connections += 1
            with connection:
                self.received.append(self._read_line(connection))
                with suppress(OSError):  # the client hangs up on a broker that misbehaves
                    self.behaviour(connection)

    @staticmethod
    def _read_line(connection: socket.socket) -> bytes:
        data = b""
        while not data.endswith(b"\n"):
            chunk = connection.recv(4096)
            if not chunk:
                break
            data += chunk
        return data


@pytest.fixture
def broker(tmp_path_factory) -> Iterator[Callable[..., StandInBroker]]:
    started: list[StandInBroker] = []

    def start(behaviour: Callable[[socket.socket], None]) -> StandInBroker:
        path = tmp_path_factory.mktemp("sock") / "broker.sock"
        listener = socket.socket(socket.AF_UNIX)
        listener.bind(str(path))
        listener.listen()
        stand_in = StandInBroker(listener, behaviour)
        stand_in.path = str(path)  # type: ignore[attr-defined]
        threading.Thread(target=stand_in.run, daemon=True).start()
        started.append(stand_in)
        return stand_in

    yield start
    for stand_in in started:
        stand_in.listener.close()


def answers(reply: dict | bytes) -> Callable[[socket.socket], None]:
    payload = reply if isinstance(reply, bytes) else json.dumps(reply).encode() + b"\n"
    return lambda connection: connection.sendall(payload)


def test_a_revert_sends_one_json_line_naming_the_operation_and_the_guest(broker):
    stand_in = broker(answers({"ok": True}))

    client.ask(client.REVERT, "win", socket_path=stand_in.path)

    assert json.loads(stand_in.received[0]) == {"op": "revert", "label": "win"}
    assert stand_in.received[0].endswith(b"\n")


def test_a_dump_names_the_task(broker):
    stand_in = broker(answers({"ok": True}))

    client.ask(client.DUMP, "win", 42, socket_path=stand_in.path)

    assert json.loads(stand_in.received[0]) == {"op": "dump", "label": "win", "task_id": 42}


def test_a_refusal_raises_with_the_brokers_reason(broker):
    stand_in = broker(answers({"ok": False, "error": "win is not a registered guest"}))

    with pytest.raises(client.MachineBrokerError, match="win is not a registered guest"):
        client.ask(client.STOP, "win", socket_path=stand_in.path)


def test_a_refusal_without_a_reason_still_raises(broker):
    stand_in = broker(answers({"ok": False}))

    with pytest.raises(client.MachineBrokerError, match="refused"):
        client.ask(client.STOP, "win", socket_path=stand_in.path)


@pytest.mark.parametrize(
    "reply",
    [b"not json\n", b"[1]\n", b'{"ok": "yes"}\n', b'{"fine": true}\n', b"", b'{"ok": true}'],
)
def test_an_answer_that_is_not_a_clear_yes_is_an_error(broker, reply):
    stand_in = broker(answers(reply))

    with pytest.raises(client.MachineBrokerError):
        client.ask(client.REVERT, "win", socket_path=stand_in.path)


def test_a_broker_that_is_not_there_is_an_error_at_once(tmp_path):
    started = time.monotonic()

    with pytest.raises(client.MachineBrokerError, match="not running"):
        client.ask(client.REVERT, "win", socket_path=str(tmp_path / "nothing.sock"))

    assert time.monotonic() - started < 1


def test_a_broker_that_never_answers_ends_at_the_timeout(broker):
    stand_in = broker(lambda _connection: time.sleep(5))
    started = time.monotonic()

    with pytest.raises(client.MachineBrokerError, match="did not answer"):
        client.ask(client.REVERT, "win", socket_path=stand_in.path, timeout=0.3)

    assert time.monotonic() - started < 2


def test_a_broker_that_trickles_bytes_still_ends_at_the_timeout(broker):
    def trickle(connection: socket.socket) -> None:
        for _ in range(100):
            connection.sendall(b" ")
            time.sleep(0.05)

    stand_in = broker(trickle)
    started = time.monotonic()

    with pytest.raises(client.MachineBrokerError):
        client.ask(client.REVERT, "win", socket_path=stand_in.path, timeout=0.5)

    assert time.monotonic() - started < 2


def test_an_endless_answer_is_cut_off(broker):
    def flood(connection: socket.socket) -> None:
        while True:
            connection.sendall(b"x" * 65536)

    stand_in = broker(flood)

    with pytest.raises(client.MachineBrokerError, match="too long"):
        client.ask(client.REVERT, "win", socket_path=stand_in.path, timeout=5)


def test_a_failed_request_is_not_sent_again(broker):
    stand_in = broker(answers({"ok": False, "error": "no"}))

    with pytest.raises(client.MachineBrokerError):
        client.ask(client.REVERT, "win", socket_path=stand_in.path)

    assert stand_in.connections == 1


def test_every_operation_has_a_timeout_and_a_dump_may_take_longest():
    assert set(client.OPERATION_TIMEOUT_S) == set(client.OPERATIONS)
    assert client.OPERATION_TIMEOUT_S[client.DUMP] > client.OPERATION_TIMEOUT_S[client.STOP]


def test_a_dump_path_of_a_task_becomes_that_tasks_id(broker):
    stand_in = broker(answers({"ok": True}))

    client.dump_memory("win", dump_path_of(17), dump_path_of, socket_path=stand_in.path)

    assert json.loads(stand_in.received[0]) == {"op": "dump", "label": "win", "task_id": 17}


@pytest.mark.parametrize(
    "path",
    [
        "/etc/cron.d/x",
        f"{ANALYSES}/17/../18/memory.dmp",
        f"{ANALYSES}/17/memory.dmp.evil",
        f"{ANALYSES}/17/sub/memory.dmp",
        f"{ANALYSES}/-1/memory.dmp",
        f"{ANALYSES}/abc/memory.dmp",
        f"{ANALYSES}/017/memory.dmp",
        f"{ANALYSES}/17 /memory.dmp",
        "/mnt/tmpfs/17.dmp",
        "relative/analyses/17/memory.dmp",
        "",
    ],
)
def test_a_path_that_is_not_an_analysis_dump_is_refused_without_asking_the_broker(broker, path):
    stand_in = broker(answers({"ok": True}))

    with pytest.raises(client.MachineBrokerError, match=r"memory\.dmp"):
        client.dump_memory("win", path, dump_path_of, socket_path=stand_in.path)

    assert stand_in.connections == 0


def test_a_path_in_another_storage_root_than_cape_uses_is_refused(broker):
    stand_in = broker(answers({"ok": True}))

    with pytest.raises(client.MachineBrokerError, match=r"memory\.dmp"):
        client.dump_memory(
            "win", "/srv/other/analyses/17/memory.dmp", dump_path_of, socket_path=stand_in.path
        )

    assert stand_in.connections == 0
