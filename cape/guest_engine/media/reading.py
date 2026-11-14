"""Looks inside a disc image without mounting it.

The image is untrusted input and the control service runs as root, so the image is never parsed
here: a short-lived child process (`reader_child.py`) opens it with pycdlib and runs the profile's
reader over it. The child gets the image as an already-open file on stdin, so it needs no file
permissions of its own, runs as `nobody` when the service is root, and is bounded in memory, CPU
time and wall-clock time. It answers with one JSON object on stdout.
"""

import json
import os
import sys
from pathlib import Path
from typing import Any, BinaryIO

from guest_engine.media.commands import CommandResult, Runner
from guest_engine.media.errors import Fault, MediaProblem

CHILD_PROGRAM = Path(__file__).with_name("reader_child.py")
READ_TIMEOUT_S = 30
CPU_LIMIT_S = 20
ADDRESS_SPACE_LIMIT_BYTES = 1 << 30
MAX_ANSWER_CHARS = 1 << 20

# What the child itself can report, besides a result; anything else it says is a failure.
CHILD_FAULTS = (Fault.NOT_AN_ISO, Fault.UNSUPPORTED_FILESYSTEM, Fault.TOOL_MISSING)

UNPRIVILEGED = (
    "setpriv",
    "--reuid",
    "nobody",
    "--regid",
    "nogroup",
    "--clear-groups",
    "--no-new-privs",
)


def read_inside(
    runner: Runner, image: Path, reader: Path, timeout_s: float = READ_TIMEOUT_S
) -> Any:
    """What `reader`'s `read(image)` returned for the disc `image`, as JSON data.

    Raises `MediaProblem` when the file is not a readable file, is not a disc image, has a
    filesystem pycdlib cannot read, or when the child fails, times out or answers nonsense.
    """
    stream = _open_regular_file(image)
    command = [
        *_privilege_drop(),
        sys.executable,
        "-I",
        str(CHILD_PROGRAM),
        str(reader),
        str(ADDRESS_SPACE_LIMIT_BYTES),
        str(CPU_LIMIT_S),
    ]
    with stream:
        finished = runner(command, timeout=timeout_s, stdin=stream)
    return _answer_of(finished)


def _open_regular_file(image: Path) -> BinaryIO:
    try:
        if not image.is_file():
            raise MediaProblem(Fault.NOT_A_FILE)
        if image.stat().st_size == 0:
            raise MediaProblem(Fault.EMPTY)
        return image.open("rb")
    except OSError as error:
        raise MediaProblem(Fault.NOT_A_FILE, detail=str(error)) from error


def _privilege_drop() -> tuple[str, ...]:
    return UNPRIVILEGED if os.geteuid() == 0 else ()


def _answer_of(finished: CommandResult) -> Any:
    failure = MediaProblem(Fault.INSPECTION_FAILED, detail=finished.stderr)
    if finished.returncode != 0 or len(finished.stdout) > MAX_ANSWER_CHARS:
        raise failure
    try:
        answer = json.loads(finished.stdout)
    except ValueError:
        raise failure from None
    if not isinstance(answer, dict):
        raise failure
    if "result" in answer:
        return answer["result"]
    fault = answer.get("fault")
    if fault in CHILD_FAULTS:
        raise MediaProblem(Fault(fault), detail=finished.stderr)
    raise failure
