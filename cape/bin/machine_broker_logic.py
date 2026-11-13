"""What the machine broker does for the `cape` user, and what it refuses.

CAPE's machinery (running as `cape`) needs three writes on a guest's libvirt domain: revert it to
its clean snapshot, power it off, and dump its memory into an analysis folder. libvirt's access
control cannot grant these without also granting root (see cape/libvirt/polkit), so `machine-broker`
does them as root, each narrowed to what CAPE legitimately does:

- the guest must be registered with CAPE (a record in the engine's registry in the `testing` or
  `ready` state), and the snapshot to revert to is the one that record names, never the client's;
- the memory dump is taken into a staging folder only root can enter, then placed in the analysis
  folder without following any link `cape` may have planted (`analysis_files.place_dump`);
- a request is one of three exact shapes, with no field to carry a path, a flag or a snapshot.
"""

import json
import os
import re
import shutil
import socket
import struct
import threading
import time
from collections.abc import Callable, Collection
from contextlib import suppress
from dataclasses import dataclass, field
from functools import partial
from pathlib import Path
from typing import Any, Protocol

from analysis_files import open_directory, place_dump, require_free_dump_slot
from finish_logic import parse_task_id
from machine_broker_client import DUMP, MAX_REQUEST_BYTES, OPERATIONS, REVERT, STOP

from guest_engine.errors import GuestNotFound
from guest_engine.media import Fault, MediaProblem, Runner
from guest_engine.profile import SLUG
from guest_engine.registration import REGISTERED_STATES
from guest_engine.registry import Registry

LIBVIRT_URI = "qemu:///system"
# A revert restores a memory snapshot (4 to 8 GiB) from disk. machine_broker_client's timeouts
# are longer than these, so a caller always hears from the broker before it gives up.
VIRSH_TIMEOUT_S = {REVERT: 600.0, STOP: 60.0, DUMP: 1200.0}
READ_TIMEOUT_S = 5.0
VIRSH_MESSAGE_LIMIT = 200
SNAPSHOT_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")

UNKNOWN_OPERATION = "the request is not one of: " + ", ".join(OPERATIONS)
FIELDS = {
    REVERT: {"op", "label"},
    STOP: {"op", "label"},
    DUMP: {"op", "label", "task_id"},
}


class Refusal(Exception):  # noqa: N818 - what the broker tells the client; the message is the answer
    """The request was refused or failed; `str()` is safe to send back to the client."""


@dataclass(frozen=True)
class Request:
    operation: str
    label: str
    task_id: int | None = None


def parse_request(raw: bytes) -> Request:
    """The request in `raw`, or a `Refusal` that does not repeat anything the client sent."""
    if len(raw) > MAX_REQUEST_BYTES:
        raise Refusal("the request is too long")
    try:
        body = json.loads(raw.decode())
    except ValueError:
        raise Refusal("the request is not valid JSON") from None
    if not isinstance(body, dict) or body.get("op") not in OPERATIONS:
        raise Refusal(UNKNOWN_OPERATION)
    operation = body["op"]
    if set(body) != FIELDS[operation]:
        wanted = ", ".join(sorted(FIELDS[operation]))
        raise Refusal(f"{operation} takes exactly the fields {wanted}")
    label = body["label"]
    if not isinstance(label, str) or not SLUG.fullmatch(label):
        raise Refusal("the label is not a guest name")
    task_id = _task_id_of(body["task_id"]) if operation == DUMP else None
    return Request(operation, label, task_id)


def _task_id_of(value: Any) -> int:
    is_integer = isinstance(value, int) and not isinstance(value, bool)
    task_id = parse_task_id(str(value)) if is_integer else None
    if not task_id:
        raise Refusal("the task id must be a positive integer")
    return task_id


class Machines(Protocol):
    def perform(self, request: Request, connected: Callable[[], bool]) -> None: ...


@dataclass
class MachineBroker:
    registry: Registry
    runner: Runner
    staging: Path
    storage: Path
    _guards: dict[str, threading.Lock] = field(default_factory=dict, init=False)
    _guards_lock: threading.Lock = field(default_factory=threading.Lock, init=False)

    def prepare_staging(self) -> None:
        """Makes the staging folder private to root and empties what a crashed run left in it."""
        self.staging.mkdir(mode=0o700, parents=True, exist_ok=True)
        with open_directory(self.staging) as folder:
            os.fchmod(folder, 0o700)
            for entry in list(os.scandir(folder)):
                if entry.is_dir(follow_symlinks=False):
                    shutil.rmtree(entry.name, dir_fd=folder)
                else:
                    os.unlink(entry.name, dir_fd=folder)

    def perform(self, request: Request, connected: Callable[[], bool]) -> None:
        """Does what `request` asks, or raises `Refusal`. One request per guest at a time.

        A request whose client has gone (it gave up waiting) is dropped instead of started: a revert
        that ran minutes late would pull the guest from under the analysis that followed.
        """
        with self._guard(request.label):
            if not connected():
                raise Refusal("the client left before the request was started")
            recorded_snapshot = self._registered_snapshot(request.label)
            if request.operation == REVERT:
                self._virsh(REVERT, "snapshot-revert", request.label, _usable(recorded_snapshot))
            elif request.operation == STOP:
                self._virsh(STOP, "destroy", request.label)
            elif request.operation == DUMP and request.task_id is not None:
                self._dump(request.label, request.task_id)
            else:
                raise Refusal(UNKNOWN_OPERATION)

    def _guard(self, label: str) -> threading.Lock:
        with self._guards_lock:
            return self._guards.setdefault(label, threading.Lock())

    def _registered_snapshot(self, label: str) -> str:
        try:
            guest = self.registry.get(label)
        except (GuestNotFound, ValueError):
            raise Refusal(f"{label} is not a registered guest") from None
        if guest.state not in REGISTERED_STATES:
            raise Refusal(f"{label} is not a registered guest")
        return guest.snapshot

    def _dump(self, label: str, task_id: int) -> None:
        _in_analysis_folder(lambda: require_free_dump_slot(self.storage, task_id))
        staged = self.staging / f"{task_id}-{os.urandom(8).hex()}.dmp"
        try:
            self._virsh(DUMP, "dump", "--memory-only", label, str(staged))
            if not staged.is_file():
                raise Refusal("libvirt wrote no memory dump")
            _in_analysis_folder(lambda: place_dump(staged, self.storage, task_id))
        finally:
            staged.unlink(missing_ok=True)

    def _virsh(self, operation: str, *arguments: str) -> None:
        command = ["virsh", "-c", LIBVIRT_URI, *arguments]
        try:
            result = self.runner(command, VIRSH_TIMEOUT_S[operation])
        except MediaProblem as problem:
            if problem.fault == Fault.TIMED_OUT:
                raise Refusal("libvirt did not finish in time") from None
            raise Refusal("virsh is not installed") from None
        if result.returncode != 0:
            raise Refusal("libvirt: " + _one_line(result.stderr))


def _in_analysis_folder(action: Callable[[], None]) -> None:
    try:
        action()
    except OSError as error:
        raise Refusal(
            f"the memory dump could not be placed in the analysis folder ({type(error).__name__})"
        ) from None


def _usable(snapshot: str) -> str:
    if not SNAPSHOT_NAME.fullmatch(snapshot):
        raise Refusal("the guest has no usable snapshot recorded")
    return snapshot


def _one_line(text: str) -> str:
    message = " ".join(text.split()) or "failed without a message"
    printable = "".join(c if c.isascii() and c.isprintable() else "?" for c in message)
    return printable[:VIRSH_MESSAGE_LIMIT]


def serve_connection(
    connection: socket.socket,
    machines: Machines,
    allowed_uids: Collection[int],
    log: Callable[[str], None],
    read_timeout_s: float = READ_TIMEOUT_S,
) -> None:
    """Answers one client: checks who it is, reads one request line, performs it, replies, logs.

    The socket's file mode already keeps other users out; this checks the peer's credentials too,
    before reading anything from it, so a socket that was ever made too open still serves only
    `allowed_uids`. Nothing the client sent is repeated in the reply or in the log.
    """
    with connection:
        uid = _peer_uid(connection)
        if uid not in allowed_uids:
            log(f"machine-broker: peer uid={uid} -> refused (not allowed)")
            _reply(connection, {"ok": False, "error": "this user may not use the broker"})
            return
        try:
            request = parse_request(_read_request(connection, read_timeout_s))
        except Refusal as refusal:
            log(f"machine-broker: invalid request uid={uid} -> refused ({refusal})")
            _reply(connection, {"ok": False, "error": str(refusal)})
            return
        waiting = partial(_client_is_waiting, connection)
        _reply(connection, _perform_and_log(machines, request, uid, waiting, log))


def turn_away(connection: socket.socket) -> None:
    """Tells a client that arrived while the broker was at capacity to come back later."""
    with connection:
        _reply(connection, {"ok": False, "error": "the machine broker is busy"})


def _perform_and_log(
    machines: Machines,
    request: Request,
    uid: int,
    connected: Callable[[], bool],
    log: Callable[[str], None],
) -> dict[str, Any]:
    prefix = f"machine-broker: {request.operation} {request.label} uid={uid} ->"
    try:
        machines.perform(request, connected)
    except Refusal as refusal:
        log(f"{prefix} refused ({refusal})")
        return {"ok": False, "error": str(refusal)}
    except Exception as bug:  # noqa: BLE001 - a bug in one request must not take the broker down
        log(f"{prefix} internal error ({type(bug).__name__})")
        return {"ok": False, "error": "internal error"}
    log(f"{prefix} ok")
    return {"ok": True}


def _client_is_waiting(connection: socket.socket) -> bool:
    """False once the client has closed its end; a client keeps it open until it has the answer."""
    patience = connection.gettimeout()
    connection.settimeout(0)
    try:
        return connection.recv(1, socket.MSG_PEEK) != b""
    except BlockingIOError:
        return True
    except OSError:
        return False
    finally:
        connection.settimeout(patience)


def _peer_uid(connection: socket.socket) -> int:
    credentials = connection.getsockopt(
        socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i")
    )
    _pid, uid, _gid = struct.unpack("3i", credentials)
    return uid


def _read_request(connection: socket.socket, timeout_s: float) -> bytes:
    deadline = time.monotonic() + timeout_s
    data = b""
    while b"\n" not in data:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise Refusal("no request arrived in time")
        connection.settimeout(remaining)
        try:
            chunk = connection.recv(MAX_REQUEST_BYTES + 1 - len(data))
        except TimeoutError:
            raise Refusal("no request arrived in time") from None
        except OSError:
            raise Refusal("the request could not be read") from None
        if not chunk:
            raise Refusal("the request is not a complete line")
        data += chunk
        if len(data) > MAX_REQUEST_BYTES and b"\n" not in data:
            raise Refusal("the request is too long")
    return data.split(b"\n", 1)[0]


def _reply(connection: socket.socket, reply: dict[str, Any]) -> None:
    with suppress(OSError):  # the client may have gone away
        connection.sendall(json.dumps(reply).encode() + b"\n")
