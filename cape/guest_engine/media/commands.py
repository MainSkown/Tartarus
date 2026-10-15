import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from guest_engine.media.errors import Fault, MediaProblem

DEFAULT_TIMEOUT_S = 60


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str
    stderr: str


class Runner(Protocol):
    """Runs a command and returns its result whatever the exit status.

    Raises `MediaProblem` when the program is not installed or runs past `timeout`.
    """

    def __call__(self, args: Sequence[str], timeout: float | None = None) -> CommandResult: ...


def run_command(args: Sequence[str], timeout: float | None = None) -> CommandResult:
    try:
        finished = subprocess.run(  # noqa: S603 - argument list, never a shell; callers pass fixed programs
            list(args),
            capture_output=True,
            text=True,
            errors="replace",
            timeout=timeout or DEFAULT_TIMEOUT_S,
            check=False,
        )
    except FileNotFoundError as error:
        raise MediaProblem(Fault.TOOL_MISSING, detail=str(args[0])) from error
    except subprocess.TimeoutExpired as error:
        raise MediaProblem(Fault.TIMED_OUT, detail=str(args[0])) from error
    return CommandResult(finished.returncode, finished.stdout, finished.stderr)
