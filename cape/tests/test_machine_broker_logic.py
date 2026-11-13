"""The machine broker's decisions: what a request may ask, which guest it may touch, and the
commands and the file placement that follow. The runner and the filesystem are stand-ins.
"""

import importlib
import json
import os
import socket
import stat
import threading
from dataclasses import dataclass, field
from pathlib import Path

import pytest
from fixtures.guest_samples import make_guest
from test_control_http import BIN  # noqa: F401 - importing it puts bin/ on sys.path

from guest_engine.media import CommandResult, Fault, MediaProblem
from guest_engine.registry import Registry

broker_logic = importlib.import_module("machine_broker_logic")
client = importlib.import_module("machine_broker_client")

HOSTILE = "../../etc/passwd\x1b[31m"


def line(**fields) -> bytes:
    return json.dumps(fields).encode() + b"\n"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (line(op="revert", label="win"), ("revert", "win", None)),
        (line(op="stop", label="lab-1"), ("stop", "lab-1", None)),
        (line(op="dump", label="win", task_id=7), ("dump", "win", 7)),
        (b'{"op":"revert","label":"win"}', ("revert", "win", None)),
    ],
)
def test_a_well_formed_request_is_understood(raw, expected):
    request = broker_logic.parse_request(raw)

    assert (request.operation, request.label, request.task_id) == expected


@pytest.mark.parametrize(
    "raw",
    [
        b"",
        b"\n",
        b"not json\n",
        b"\xff\xfe\n",
        b"[]\n",
        b'"revert"\n',
        b"null\n",
        line(label="win"),
        line(op="start", label="win"),
        line(op="define", label="win"),
        line(op=None, label="win"),
        line(op="revert"),
        line(op="revert", label=None),
        line(op="revert", label=7),
        line(op="revert", label=["win"]),
        line(op="dump", label="win"),
    ],
)
def test_a_request_that_is_not_one_of_the_three_operations_is_refused(raw):
    with pytest.raises(broker_logic.Refusal):
        broker_logic.parse_request(raw)


@pytest.mark.parametrize(
    "label",
    [
        HOSTILE,
        "../win",
        "win/../lab1",
        "-win",
        "--help",
        "Win",
        "a",
        "w" * 33,
        "win ",
        "win\n",
        "win;reboot",
        "win,lab1",
        "$(id)",
        "win\x00",
        "",
        "1win",
    ],
)
def test_a_label_that_is_not_a_guest_name_is_refused_before_it_reaches_a_command(label):
    with pytest.raises(broker_logic.Refusal, match="not a guest name"):
        broker_logic.parse_request(line(op="stop", label=label))


@pytest.mark.parametrize(
    "extra",
    [
        {"snapshot": "evil"},
        {"snapshot": "tartarus-clean"},
        {"path": "/etc/passwd"},
        {"flags": 1},
        {"task_id": 7},
    ],
)
def test_a_field_the_operation_does_not_take_is_refused_not_ignored(extra):
    with pytest.raises(broker_logic.Refusal, match="takes exactly"):
        broker_logic.parse_request(line(op="revert", label="win", **extra))


@pytest.mark.parametrize(
    "extra",
    [{"snapshot": "evil"}, {"path": "/etc/passwd"}, {"dest": "/x"}],
)
def test_a_dump_takes_no_path_from_the_client(extra):
    with pytest.raises(broker_logic.Refusal, match="takes exactly"):
        broker_logic.parse_request(line(op="dump", label="win", task_id=7, **extra))


@pytest.mark.parametrize(
    "task_id",
    ["7", "07", 7.0, 7.5, True, False, None, [7], {"id": 7}, 0, -1, 10**18, 10**30],
)
def test_a_task_id_that_is_not_a_plain_positive_integer_is_refused(task_id):
    with pytest.raises(broker_logic.Refusal, match="task id"):
        broker_logic.parse_request(line(op="dump", label="win", task_id=task_id))


def test_a_request_longer_than_the_protocols_limit_is_refused_unread():
    raw = line(op="stop", label="win", padding="x" * client.MAX_REQUEST_BYTES)

    with pytest.raises(broker_logic.Refusal, match="too long"):
        broker_logic.parse_request(raw)


def test_a_refusal_never_repeats_what_the_client_sent():
    for raw in (line(op=HOSTILE, label="win"), line(op="stop", label=HOSTILE), HOSTILE.encode()):
        with pytest.raises(broker_logic.Refusal) as refusal:
            broker_logic.parse_request(raw)

        assert "etc" not in str(refusal.value)
        assert "\x1b" not in str(refusal.value)


@dataclass
class Virsh:
    """Stands in for virsh as root: records every command, and can write a dump or fail."""

    calls: list[tuple[list[str], float | None]] = field(default_factory=list)
    result: CommandResult = field(default_factory=lambda: CommandResult(0, "", ""))
    raises: Exception | None = None
    writes_dump: bytes | None = b"core-bytes"
    lock: threading.Lock = field(default_factory=threading.Lock)

    def __call__(self, args, timeout=None):
        with self.lock:
            self.calls.append((list(args), timeout))
        if self.raises:
            raise self.raises
        if "dump" in args and self.writes_dump is not None:
            Path(args[-1]).write_bytes(self.writes_dump)
        return self.result


@pytest.fixture
def registry(tmp_path):
    guests = Registry(tmp_path / "guests")
    guests.create(make_guest("win", "192.168.150.11", state="ready"))
    guests.create(make_guest("testing-1", "192.168.150.12", state="testing"))
    guests.create(make_guest("building", "192.168.150.13", state="building"))
    guests.create(make_guest("broken", "192.168.150.14", state="failed"))
    guests.create(make_guest("other", "192.168.150.15", state="ready", snapshot="baseline-2"))
    return guests


@pytest.fixture
def storage(tmp_path):
    (tmp_path / "storage" / "analyses" / "7").mkdir(parents=True)
    return tmp_path / "storage"


@pytest.fixture
def virsh():
    return Virsh()


@pytest.fixture
def machines(registry, virsh, storage, tmp_path):
    staging = tmp_path / "staging"
    machines = broker_logic.MachineBroker(registry, virsh, staging, storage)
    machines.prepare_staging()
    return machines


def ask(machines, connected=lambda: True, **fields):
    return machines.perform(broker_logic.parse_request(line(**fields)), connected)


def test_a_revert_goes_to_the_snapshot_the_guests_record_names(machines, virsh):
    ask(machines, op="revert", label="win")

    assert virsh.calls == [
        (
            ["virsh", "-c", "qemu:///system", "snapshot-revert", "win", "tartarus-clean"],
            broker_logic.VIRSH_TIMEOUT_S["revert"],
        )
    ]


def test_each_guest_reverts_to_its_own_recorded_snapshot(machines, virsh):
    ask(machines, op="revert", label="other")

    assert virsh.calls[0][0][-2:] == ["other", "baseline-2"]


@pytest.mark.parametrize("label", ["win", "testing-1"])
def test_a_guest_that_is_registered_with_cape_may_be_reverted_stopped_and_dumped(
    machines, virsh, label
):
    ask(machines, op="revert", label=label)
    ask(machines, op="stop", label=label)
    ask(machines, op="dump", label=label, task_id=7)

    assert [call[0][3] for call in virsh.calls] == ["snapshot-revert", "destroy", "dump"]


@pytest.mark.parametrize("operation", ["revert", "stop", "dump"])
@pytest.mark.parametrize("label", ["building", "broken", "nobody", "lab-9"])
def test_a_guest_that_is_not_registered_with_cape_is_refused_and_virsh_not_run(
    machines, virsh, operation, label
):
    extra = {"task_id": 7} if operation == "dump" else {}

    with pytest.raises(broker_logic.Refusal, match="not a registered guest"):
        ask(machines, op=operation, label=label, **extra)

    assert virsh.calls == []


def test_a_guest_whose_record_cannot_be_read_is_not_registered(machines, virsh, tmp_path):
    (tmp_path / "guests" / "win" / "guest.json").write_text("{not json")

    with pytest.raises(broker_logic.Refusal, match="not a registered guest"):
        ask(machines, op="stop", label="win")

    assert virsh.calls == []


@pytest.mark.parametrize("snapshot", ["", "-x", "--force", "a b", "a;b", "../x", "x" * 65])
def test_a_recorded_snapshot_name_that_cannot_be_an_argument_is_refused(
    machines, virsh, registry, snapshot
):
    registry.update("win", snapshot=snapshot)

    with pytest.raises(broker_logic.Refusal, match="no usable snapshot"):
        ask(machines, op="revert", label="win")

    assert virsh.calls == []


def test_a_stop_destroys_the_domain(machines, virsh):
    ask(machines, op="stop", label="win")

    assert virsh.calls == [
        (
            ["virsh", "-c", "qemu:///system", "destroy", "win"],
            broker_logic.VIRSH_TIMEOUT_S["stop"],
        )
    ]


def test_virsh_failing_is_reported_with_its_message_made_printable_on_one_line(machines, virsh):
    virsh.result = CommandResult(
        1, "", "error: Failed to \x1b[31mrevert\n\nerror: Requested operation is not valid\n"
    )

    with pytest.raises(broker_logic.Refusal) as refusal:
        ask(machines, op="revert", label="win")

    assert str(refusal.value) == (
        "libvirt: error: Failed to ?[31mrevert error: Requested operation is not valid"
    )


def test_a_long_virsh_message_is_cut_short(machines, virsh):
    virsh.result = CommandResult(1, "", "error: " + "x" * 1000)

    with pytest.raises(broker_logic.Refusal) as refusal:
        ask(machines, op="revert", label="win")

    assert len(str(refusal.value)) == len("libvirt: ") + broker_logic.VIRSH_MESSAGE_LIMIT


def test_a_virsh_that_says_nothing_is_still_reported(machines, virsh):
    virsh.result = CommandResult(1, "", "")

    with pytest.raises(broker_logic.Refusal, match="failed without a message"):
        ask(machines, op="revert", label="win")


def test_virsh_timing_out_is_reported_as_taking_too_long(machines, virsh):
    virsh.raises = MediaProblem(Fault.TIMED_OUT, detail="virsh")

    with pytest.raises(broker_logic.Refusal, match="did not finish in time"):
        ask(machines, op="revert", label="win")


def test_virsh_missing_is_reported(machines, virsh):
    virsh.raises = MediaProblem(Fault.TOOL_MISSING, detail="virsh")

    with pytest.raises(broker_logic.Refusal, match="virsh is not installed"):
        ask(machines, op="stop", label="win")


def staged_names(tmp_path):
    return sorted(path.name for path in (tmp_path / "staging").iterdir())


def test_a_dump_is_taken_into_the_staging_folder_and_placed_in_the_analysis(
    machines, virsh, storage, tmp_path
):
    ask(machines, op="dump", label="win", task_id=7)

    command, timeout = virsh.calls[0]
    staged_path = command[-1]
    assert command[:6] == ["virsh", "-c", "qemu:///system", "dump", "--memory-only", "win"]
    assert os.path.dirname(staged_path) == str(tmp_path / "staging")
    assert timeout == broker_logic.VIRSH_TIMEOUT_S["dump"]
    assert (storage / "analyses" / "7" / "memory.dmp").read_bytes() == b"core-bytes"
    assert staged_names(tmp_path) == []


def test_each_dump_is_staged_under_a_name_of_its_own(machines, virsh, storage):
    (storage / "analyses" / "8").mkdir()

    ask(machines, op="dump", label="win", task_id=7)
    ask(machines, op="dump", label="win", task_id=8)

    assert virsh.calls[0][0][-1] != virsh.calls[1][0][-1]


def test_a_dump_that_virsh_fails_is_not_placed_and_leaves_nothing_staged(
    machines, virsh, storage, tmp_path
):
    virsh.result = CommandResult(1, "", "error: cannot dump")

    with pytest.raises(broker_logic.Refusal, match="cannot dump"):
        ask(machines, op="dump", label="win", task_id=7)

    assert not (storage / "analyses" / "7" / "memory.dmp").exists()
    assert staged_names(tmp_path) == []


def test_a_dump_virsh_never_wrote_is_an_error(machines, virsh, storage, tmp_path):
    virsh.writes_dump = None

    with pytest.raises(broker_logic.Refusal, match="no memory dump"):
        ask(machines, op="dump", label="win", task_id=7)

    assert not (storage / "analyses" / "7" / "memory.dmp").exists()


def test_an_analysis_folder_that_cannot_take_the_dump_is_an_error_and_leaves_nothing_staged(
    machines, virsh, tmp_path
):
    with pytest.raises(broker_logic.Refusal, match="analysis folder") as refusal:
        ask(machines, op="dump", label="win", task_id=99)

    assert "FileNotFoundError" in str(refusal.value)
    assert virsh.calls == []
    assert staged_names(tmp_path) == []


def test_a_dump_is_not_even_taken_when_the_analysis_already_has_one(machines, virsh, storage):
    (storage / "analyses" / "7" / "memory.dmp").write_bytes(b"first")

    with pytest.raises(broker_logic.Refusal, match="analysis folder") as refusal:
        ask(machines, op="dump", label="win", task_id=7)

    assert "FileExistsError" in str(refusal.value)
    assert virsh.calls == []


def test_an_analysis_folder_that_is_a_symlink_gets_nothing(machines, virsh, storage, tmp_path):
    victim = tmp_path / "victim"
    victim.mkdir()
    (storage / "analyses" / "7").rmdir()
    (storage / "analyses" / "7").symlink_to(victim)

    with pytest.raises(broker_logic.Refusal, match="analysis folder"):
        ask(machines, op="dump", label="win", task_id=7)

    assert list(victim.iterdir()) == []
    assert staged_names(tmp_path) == []


def test_the_staging_folder_is_private_to_root_and_emptied_of_what_a_crash_left(machines, tmp_path):
    staging = tmp_path / "staging"
    (staging / "7-old.dmp").write_bytes(b"left over")
    (staging / "link").symlink_to(tmp_path)
    (staging / "folder").mkdir()
    (staging / "folder" / "inside").write_text("x")

    machines.prepare_staging()

    assert list(staging.iterdir()) == []
    assert tmp_path.is_dir()
    assert stat.S_IMODE(staging.stat().st_mode) == 0o700


def test_a_staging_folder_that_is_a_symlink_is_refused(registry, virsh, storage, tmp_path):
    (tmp_path / "elsewhere").mkdir()
    (tmp_path / "staging").symlink_to(tmp_path / "elsewhere")
    machines = broker_logic.MachineBroker(registry, virsh, tmp_path / "staging", storage)

    with pytest.raises(OSError):  # noqa: PT011 - any refusal to use a link is the point
        machines.prepare_staging()


def test_two_requests_for_one_guest_never_run_at_once(machines, virsh):
    inside = threading.Semaphore(0)
    release = threading.Event()
    running = 0
    most = 0
    guard = threading.Lock()

    def slow(args, timeout=None):
        nonlocal running, most
        with guard:
            running += 1
            most = max(most, running)
        inside.release()
        release.wait(2)
        with guard:
            running -= 1
        return CommandResult(0, "", "")

    machines.runner = slow
    threads = [
        threading.Thread(target=ask, args=(machines,), kwargs={"op": "stop", "label": "win"})
        for _ in range(2)
    ]
    for thread in threads:
        thread.start()
    assert inside.acquire(timeout=2)
    assert not inside.acquire(timeout=0.3)
    release.set()
    for thread in threads:
        thread.join(3)

    assert most == 1


def test_requests_for_different_guests_run_at_the_same_time(machines):
    both_inside = threading.Barrier(2, timeout=2)

    def meet(args, timeout=None):
        both_inside.wait()
        return CommandResult(0, "", "")

    machines.runner = meet
    errors: list[BaseException] = []

    def guarded(label):
        try:
            ask(machines, op="stop", label=label)
        except BaseException as error:  # noqa: BLE001 - reported to the test thread
            errors.append(error)

    threads = [threading.Thread(target=guarded, args=(label,)) for label in ("win", "testing-1")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(3)

    assert errors == []


def test_the_broker_gives_virsh_less_time_than_the_client_waits_for_its_answer():
    for operation in client.OPERATIONS:
        assert broker_logic.VIRSH_TIMEOUT_S[operation] < client.OPERATION_TIMEOUT_S[operation]


class Connection:
    """One client of the broker: a socketpair, whose far end plays the client."""

    def __init__(self):
        self.server, self.client = socket.socketpair()

    def send(self, data: bytes) -> None:
        self.client.sendall(data)

    def reply(self) -> dict:
        self.client.settimeout(3)
        data = b""
        while not data.endswith(b"\n"):
            chunk = self.client.recv(4096)
            if not chunk:
                break
            data += chunk
        return json.loads(data)


@pytest.fixture
def connection():
    pair = Connection()
    yield pair
    pair.server.close()
    pair.client.close()


class Spy:
    def __init__(self, error: Exception | None = None):
        self.performed = []
        self.connected = []
        self.error = error

    def perform(self, request, connected):
        self.performed.append(request)
        self.connected.append(connected())
        if self.error:
            raise self.error


def serve(connection, spy, *, allowed=None, **options):
    logged: list[str] = []
    broker_logic.serve_connection(
        connection.server,
        spy,
        allowed if allowed is not None else {os.getuid()},
        logged.append,
        **options,
    )
    return logged


def test_a_permitted_peers_request_is_performed_answered_and_logged(connection):
    connection.send(line(op="stop", label="win"))
    spy = Spy()

    logged = serve(connection, spy)

    assert connection.reply() == {"ok": True}
    assert [(r.operation, r.label) for r in spy.performed] == [("stop", "win")]
    assert logged == [f"machine-broker: stop win uid={os.getuid()} -> ok"]


def test_a_peer_whose_uid_is_not_allowed_is_refused_and_nothing_is_performed(connection):
    connection.send(line(op="stop", label="win"))
    spy = Spy()

    logged = serve(connection, spy, allowed={os.getuid() + 1})

    assert connection.reply() == {"ok": False, "error": "this user may not use the broker"}
    assert spy.performed == []
    assert logged == [f"machine-broker: peer uid={os.getuid()} -> refused (not allowed)"]


def test_the_peer_is_checked_before_a_byte_of_its_request_is_read(connection):
    spy = Spy()

    serve(connection, spy, allowed=set(), read_timeout_s=0.05)

    assert connection.reply()["ok"] is False
    assert spy.performed == []


def test_a_refusal_is_answered_with_its_reason_and_logged_by_outcome(connection):
    connection.send(line(op="stop", label="win"))
    spy = Spy(broker_logic.Refusal("win is not a registered guest"))

    logged = serve(connection, spy)

    assert connection.reply() == {"ok": False, "error": "win is not a registered guest"}
    assert logged == [
        f"machine-broker: stop win uid={os.getuid()} -> refused (win is not a registered guest)"
    ]


def test_a_malformed_request_is_answered_and_logged_without_its_bytes(connection):
    connection.send(HOSTILE.encode() + b"\n")
    spy = Spy()

    logged = serve(connection, spy)

    assert connection.reply()["ok"] is False
    assert spy.performed == []
    assert len(logged) == 1
    assert "etc" not in logged[0]
    assert "\x1b" not in logged[0]
    assert logged[0].startswith(f"machine-broker: invalid request uid={os.getuid()} -> refused")


def test_a_request_with_a_bad_label_is_logged_without_the_label(connection):
    connection.send(line(op="stop", label=HOSTILE))

    logged = serve(connection, Spy())

    assert "etc" not in logged[0]


def test_an_oversized_request_is_refused_after_reading_only_what_the_limit_allows(connection):
    connection.send(b"x" * (client.MAX_REQUEST_BYTES * 10))
    spy = Spy()

    logged = serve(connection, spy)

    assert connection.reply() == {"ok": False, "error": "the request is too long"}
    assert spy.performed == []
    assert "too long" in logged[0]


def test_a_client_that_sends_nothing_is_dropped_at_the_read_timeout(connection):
    spy = Spy()

    logged = serve(connection, spy, read_timeout_s=0.2)

    assert connection.reply() == {"ok": False, "error": "no request arrived in time"}
    assert spy.performed == []
    assert "no request" in logged[0]


def test_a_client_that_trickles_its_request_is_dropped_at_the_read_timeout(connection):
    connection.send(b'{"op":')
    spy = Spy()

    serve(connection, spy, read_timeout_s=0.2)

    assert connection.reply()["ok"] is False
    assert spy.performed == []


def test_a_client_that_hangs_up_without_a_newline_gets_no_operation_performed(connection):
    connection.send(line(op="stop", label="win").rstrip(b"\n"))
    connection.client.shutdown(socket.SHUT_WR)
    spy = Spy()

    serve(connection, spy)

    assert spy.performed == []


def test_a_bug_in_an_operation_is_answered_as_an_internal_error_and_logged_by_type(connection):
    connection.send(line(op="stop", label="win"))
    spy = Spy(RuntimeError("secret detail"))

    logged = serve(connection, spy)

    assert connection.reply() == {"ok": False, "error": "internal error"}
    assert logged == [
        f"machine-broker: stop win uid={os.getuid()} -> internal error (RuntimeError)"
    ]


def test_a_request_is_started_only_while_its_client_is_still_waiting(connection):
    connection.send(line(op="stop", label="win"))
    spy = Spy()

    serve(connection, spy)

    assert spy.connected == [True]


def test_a_client_that_left_before_the_answer_does_not_break_the_server(connection):
    connection.send(line(op="stop", label="win"))
    connection.client.close()
    spy = Spy()

    serve(connection, spy)

    assert spy.connected == [False]


def test_a_request_whose_client_left_is_not_performed_at_all(machines, virsh):
    with pytest.raises(broker_logic.Refusal, match="client left"):
        ask(machines, connected=lambda: False, op="revert", label="win")

    assert virsh.calls == []


def test_a_request_that_waited_for_its_guest_is_dropped_if_its_client_left_meanwhile(
    machines, virsh
):
    still_waiting = [True]
    holding = machines._guard("win")
    holding.acquire()
    outcome: list[object] = []

    def second():
        try:
            ask(machines, connected=lambda: still_waiting[0], op="revert", label="win")
        except broker_logic.Refusal as refusal:
            outcome.append(str(refusal))

    thread = threading.Thread(target=second)
    thread.start()
    still_waiting[0] = False
    holding.release()
    thread.join(3)

    assert outcome == ["the client left before the request was started"]
    assert virsh.calls == []
