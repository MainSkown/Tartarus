"""The machine broker's wire protocol, and the client CAPE's patched libvirt machinery uses.

The broker (`machine-broker`) does the three writes CAPE needs from libvirt, as root, so that the
unprivileged `cape` user has no libvirt write permission at all. One request per connection to
`SOCKET_PATH`: a line of JSON in, a line of JSON out.

    {"op": "revert", "label": "win"}                   ->  {"ok": true}
    {"op": "stop", "label": "win"}                     ->  {"ok": true}
    {"op": "dump", "label": "win", "task_id": 7}       ->  {"ok": false, "error": "..."}

This file ships into CAPE's tree (`lib/cuckoo/common/`) and into the broker's own directory, so it
uses the standard library only and is the one place the protocol is written down.
"""

import json
import re
import socket
import time
from collections.abc import Callable

SOCKET_PATH = "/run/tartarus/machine-broker.sock"

REVERT = "revert"
STOP = "stop"
DUMP = "dump"
OPERATIONS = (REVERT, STOP, DUMP)

MAX_REQUEST_BYTES = 512
MAX_REPLY_BYTES = 4096

# How long a caller waits for the answer: the time the broker allows the operation (a revert
# restores a memory snapshot of 4 to 8 GiB; a dump writes and then copies that much) plus a margin.
OPERATION_TIMEOUT_S = {REVERT: 660.0, STOP: 90.0, DUMP: 1800.0}

ANALYSIS_DUMP_PATH = re.compile(r"/.*/analyses/([1-9][0-9]{0,17})/memory\.dmp")


class MachineBrokerError(Exception):
    """The broker refused the request, failed it, or could not be reached."""


def encode_request(operation: str, label: str, task_id: int | None = None) -> bytes:
    request: dict[str, object] = {"op": operation, "label": label}
    if task_id is not None:
        request["task_id"] = task_id
    return json.dumps(request, separators=(",", ":")).encode() + b"\n"


def ask(
    operation: str,
    label: str,
    task_id: int | None = None,
    *,
    socket_path: str = SOCKET_PATH,
    timeout: float | None = None,
) -> None:
    """Asks the broker once; returns when it did the work and raises `MachineBrokerError` if not.

    Never retried: a revert that was done but whose answer got lost must not be done twice.
    """
    deadline = time.monotonic() + (
        timeout if timeout is not None else OPERATION_TIMEOUT_S[operation]
    )
    try:
        with socket.socket(socket.AF_UNIX) as connection:
            connection.settimeout(max(deadline - time.monotonic(), 0.001))
            connection.connect(socket_path)
            connection.sendall(encode_request(operation, label, task_id))
            raw = _read_line(connection, deadline)
    except (FileNotFoundError, ConnectionRefusedError) as error:
        raise MachineBrokerError("the machine broker is not running") from error
    except TimeoutError as error:
        raise MachineBrokerError("the machine broker did not answer in time") from error
    except OSError as error:
        raise MachineBrokerError(
            f"the machine broker cannot be reached ({error.strerror})"
        ) from error
    _check_reply(raw)


def dump_memory(
    label: str, path: str, dump_path_of: Callable[[int], str], **options: object
) -> None:
    """Dumps the memory of `label` to `path`, which must be one task's `memory.dmp`.

    `dump_path_of` is CAPE's own `get_memdump_path` for the analysis folder: the id is read out of
    `path` and the broker is asked only if CAPE would have built exactly this path for it.
    """
    found = ANALYSIS_DUMP_PATH.fullmatch(path)
    task_id = int(found.group(1)) if found else None
    if task_id is None or dump_path_of(task_id) != path:
        raise MachineBrokerError("only the memory.dmp of an analysis folder can be dumped to")
    ask(DUMP, label, task_id, **options)  # type: ignore[arg-type]


def _read_line(connection: socket.socket, deadline: float) -> bytes:
    data = b""
    while not data.endswith(b"\n"):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError
        connection.settimeout(remaining)
        chunk = connection.recv(MAX_REPLY_BYTES)
        if not chunk:
            break
        data += chunk
        if len(data) > MAX_REPLY_BYTES:
            raise MachineBrokerError("the machine broker's answer is too long")
    return data


def _check_reply(raw: bytes) -> None:
    try:
        reply = json.loads(raw) if raw.endswith(b"\n") else None
    except ValueError:
        reply = None
    if not isinstance(reply, dict) or not isinstance(reply.get("ok"), bool):
        raise MachineBrokerError("the machine broker's answer was not understood")
    if not reply["ok"]:
        error = reply.get("error")
        raise MachineBrokerError(error if isinstance(error, str) else "the machine broker refused")
