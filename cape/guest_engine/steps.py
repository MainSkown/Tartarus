"""The step contract: how the sequencer runs one step and reads what it says.

A step is an executable. It gets its inputs from `TT_*` environment variables (paths to files, never
values interpolated into a command line), writes protocol lines to stdout or stderr, and ends with
an exit code:

    STEP <text>          what the step is doing now
    PROGRESS <0-100>     how far along this step is
    LOG <text>           a line for the build log
    PAUSE <text>         instructions for the analyst; used together with exit code 75
    anything else        a line for the build log

    exit 0 = done, 75 = waiting for the user, anything else = failed
"""

import contextlib
import os
import signal
import subprocess
import threading
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import IO

PAUSE_EXIT_CODE = 75
MAX_LINE_LENGTH = 4000
MAX_PROGRESS = 100
MASK = "***"
INHERITED_VARIABLES = ("PATH", "LANG", "LC_ALL", "TZ", "HOME")
DEFAULT_PATH = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"


@dataclass(frozen=True)
class StepTitle:
    text: str


@dataclass(frozen=True)
class Progress:
    percent: int


@dataclass(frozen=True)
class Log:
    text: str


@dataclass(frozen=True)
class PauseRequest:
    instructions: str


type StepEvent = StepTitle | Progress | Log | PauseRequest


def parse_line(line: str) -> StepEvent:
    keyword, _, rest = line.partition(" ")
    if keyword == "STEP":
        return StepTitle(rest)
    if keyword == "PROGRESS" and rest.isascii() and rest.isdigit() and int(rest) <= MAX_PROGRESS:
        return Progress(int(rest))
    if keyword == "LOG":
        return Log(rest)
    if keyword == "PAUSE":
        return PauseRequest(rest)
    return Log(line)


class Redactor:
    """Masks every occurrence of the guest's secrets before a line is logged or shown."""

    def __init__(self, secrets: Iterable[str]) -> None:
        self._secrets = sorted({secret for secret in secrets if secret}, key=len, reverse=True)

    def __call__(self, text: str) -> str:
        for secret in self._secrets:
            text = text.replace(secret, MASK)
        return text


@dataclass(frozen=True)
class StepPaths:
    """The files and folders of one build that a step is told about."""

    guest_dir: Path
    guest_json: Path
    profile_dir: Path
    state_file: Path
    build_dir: Path
    log: Path
    context_json: Path


def step_environment(
    paths: StepPaths, *, step: str, build_id: str, inherited: Mapping[str, str]
) -> dict[str, str]:
    """What a step may see: a few harmless variables of the service and the `TT_*` ones.

    The service's own environment holds the control token and the CAPE API token, so it is not
    handed on wholesale.
    """
    environment = {name: inherited[name] for name in INHERITED_VARIABLES if name in inherited}
    environment.setdefault("PATH", DEFAULT_PATH)
    environment.update(
        TT_GUEST_DIR=str(paths.guest_dir),
        TT_GUEST_JSON=str(paths.guest_json),
        TT_PROFILE_DIR=str(paths.profile_dir),
        TT_STATE_FILE=str(paths.state_file),
        TT_BUILD_DIR=str(paths.build_dir),
        TT_CONTEXT_JSON=str(paths.context_json),
        TT_STEP=step,
        TT_BUILD_ID=build_id,
        TT_LOG=str(paths.log),
    )
    return environment


@dataclass(frozen=True)
class StepOutcome:
    exit_code: int | None
    timed_out: bool
    start_error: str = ""


def run_step(
    command: Sequence[str],
    environment: Mapping[str, str],
    *,
    timeout_s: float,
    on_line: Callable[[str], None],
) -> StepOutcome:
    """Run `command` (an argument list, never a shell string), giving each output line to `on_line`.

    The step runs in a process group of its own. Past `timeout_s` the whole group is killed, and
    it is killed when the step ends too, so a helper it left behind cannot hold the output open.
    """
    try:
        process = subprocess.Popen(  # noqa: S603 - argument list, the step path comes from a profile
            list(command),
            env=dict(environment),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            errors="replace",
            start_new_session=True,
        )
    except OSError as error:
        return StepOutcome(None, False, start_error=f"{command[0]}: {error.strerror}")
    reader = threading.Thread(target=_deliver, args=(process, on_line), daemon=True)
    reader.start()
    timed_out = threading.Event()

    def stop_on_timeout() -> None:
        timed_out.set()
        _kill_group(process)

    timer = threading.Timer(timeout_s, stop_on_timeout)
    timer.start()
    try:
        # WNOWAIT leaves the leader unreaped, so its group id cannot be reused before the kill.
        os.waitid(os.P_PID, process.pid, os.WEXITED | os.WNOWAIT)
    finally:
        timer.cancel()
        _kill_group(process)
    exit_code = process.wait()
    reader.join()
    return StepOutcome(exit_code, timed_out.is_set())


def _kill_group(process: subprocess.Popen[str]) -> None:
    with contextlib.suppress(ProcessLookupError):
        os.killpg(process.pid, signal.SIGKILL)


def _deliver(process: subprocess.Popen[str], on_line: Callable[[str], None]) -> None:
    if process.stdout is None:
        return
    with process.stdout:
        for line in _lines(process.stdout):
            on_line(line)


def _lines(stream: IO[str]) -> Iterator[str]:
    while chunk := stream.readline(MAX_LINE_LENGTH + 1):
        if chunk.endswith("\n"):
            yield chunk[:-1].removesuffix("\r")
        elif len(chunk) > MAX_LINE_LENGTH:
            yield chunk[:MAX_LINE_LENGTH]
            _discard_rest_of_line(stream)
        else:
            yield chunk


def _discard_rest_of_line(stream: IO[str]) -> None:
    while (chunk := stream.readline(MAX_LINE_LENGTH)) and not chunk.endswith("\n"):
        pass
