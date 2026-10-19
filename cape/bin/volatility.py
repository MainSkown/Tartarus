"""The one place a Volatility3 command line is built and its output read.

Used by `memory_logic`. The runner is injected, so everything here is tested without Volatility
installed; `run_command` is the real one, which starts `vol` as the unprivileged `cape` user.
"""

import json
import re
import subprocess
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

# `uv pip install` puts the console script in the CAPE venv, next to the libraries it needs.
VOLATILITY_COMMAND = "/opt/CAPEv2/.venv/bin/vol"
NO_SYMBOLS = "no symbols for this Windows build"
# The JSON of 144 processes is 45 KB and the largest plugin here a few hundred; a hostile
# dump must not be able to make the service hold gigabytes of someone else's output.
MAX_OUTPUT_BYTES = 64 * 1024 * 1024
ERROR_DETAIL_LIMIT = 200
BANNER = re.compile(r"^Volatility 3 Framework (\S+)$", re.MULTILINE)
# What `vol` prints when it cannot build the kernel layer or find its symbol table: the same
# failure whether the ISF is missing or belongs to another build.
UNSATISFIED_MARKERS = (
    "Unable to validate the plugin requirements",
    "requirement was not fulfilled",
)


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str
    stderr: str
    timed_out: bool = False


type Runner = Callable[[Sequence[str], float], CommandResult]


@dataclass(frozen=True)
class PluginRun:
    """`rows` is None exactly when `error` is set."""

    rows: list[dict] | None
    seconds: float
    error: str | None
    version: str | None = None


class VolatilityUnavailableError(Exception):
    """`vol` could not be started at all, so no plugin of this run can work."""


def run_command(
    command: Sequence[str],
    timeout: float,
    *,
    user: str | None = None,
    environment: Mapping[str, str] | None = None,
) -> CommandResult:
    """Runs `command` to completion or kills it after `timeout` seconds.

    The child gets only `environment`, never the service's own (which holds the bearer token),
    and no stdin.
    """
    try:
        done = subprocess.run(  # noqa: S603 - the command is built by `Volatility.command`
            command,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            stdin=subprocess.DEVNULL,
            env={} if environment is None else dict(environment),
            cwd="/",
            user=user,
            group=user,
            extra_groups=[] if user else None,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return CommandResult(-9, "", "", timed_out=True)
    return CommandResult(done.returncode, done.stdout, done.stderr)


class Volatility:
    def __init__(
        self,
        dump: Path,
        symbols_directory: Path,
        runner: Runner,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.dump = dump
        self.symbols_directory = symbols_directory
        self.runner = runner
        self.clock = clock

    def command(self, plugin: str, pids: Sequence[int] = ()) -> list[str]:
        # --offline: the cape container has internet access, and without it a missing ISF would
        # make Volatility fetch the kernel's PDB from Microsoft on its own.
        command = [
            VOLATILITY_COMMAND,
            "-q",
            "--offline",
            "-s",
            str(self.symbols_directory),
            "-f",
            str(self.dump),
            "-r",
            "json",
            plugin,
        ]
        if pids:
            command += ["--pid", *map(str, pids)]
        return command

    def run(self, plugin: str, timeout: float, pids: Sequence[int] = ()) -> PluginRun:
        started = self.clock()
        try:
            result = self.runner(self.command(plugin, pids), timeout)
        except OSError as unstartable:
            raise VolatilityUnavailableError(
                f"volatility could not be started ({type(unstartable).__name__})"
            ) from unstartable
        seconds = self.clock() - started
        version = _banner_version(result.stderr)
        error = _error_of(result, timeout)
        rows = None if error else _rows_of(result.stdout)
        if not error and rows is None:
            error = "volatility printed output that is not a list of rows"
        return PluginRun(rows, seconds, error, version)


def _error_of(result: CommandResult, timeout: float) -> str | None:
    if result.timed_out:
        return f"timed out after {timeout:.0f} s"
    if result.returncode != 0:
        return _failure_message(result)
    if len(result.stdout) > MAX_OUTPUT_BYTES:
        return f"volatility printed more than {MAX_OUTPUT_BYTES} bytes, larger than is kept"
    return None


def _failure_message(result: CommandResult) -> str:
    output = result.stdout + result.stderr
    if any(marker in output for marker in UNSATISFIED_MARKERS):
        return NO_SYMBOLS
    message = f"volatility exited with status {result.returncode}"
    lines = [line.strip() for line in result.stderr.splitlines() if line.strip()]
    return f"{message}: {lines[-1][:ERROR_DETAIL_LIMIT]}" if lines else message


def _rows_of(stdout: str) -> list[dict] | None:
    try:
        rows = json.loads(stdout)
    except ValueError:
        return None
    if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
        return None
    return rows


def _banner_version(stderr: str) -> str | None:
    found = BANNER.search(stderr)
    return found.group(1) if found else None
