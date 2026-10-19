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
VOLATILITY_PYTHON = "/opt/CAPEv2/.venv/bin/python"
# On the `guest-images` volume next to the guest registry, so it survives `docker compose down`;
# Volatility looks for ISF files in its `windows/` subdirectory.
SYMBOLS_DIRECTORY = Path("/var/lib/libvirt/tartarus/symbols")
CAPE_USER = "cape"
# All that a Volatility process gets: the service's own environment holds the bearer token. HOME
# is where Volatility keeps its identifier cache.
CAPE_ENVIRONMENT = {"HOME": "/home/cape", "PATH": "/usr/local/bin:/usr/bin:/bin", "LANG": "C.UTF-8"}
NO_SYMBOLS = "no symbols for this Windows build"
# The JSON of 144 processes is 45 KB and the largest plugin here a few hundred; a hostile
# dump must not be able to make the service hold gigabytes of someone else's output.
MAX_OUTPUT_BYTES = 64 * 1024 * 1024
ERROR_DETAIL_LIMIT = 200
BANNER = re.compile(r"^Volatility 3 Framework (\S+)$", re.MULTILINE)
# What `pdbutil.load_windows_symbol_table` logs at INFO when it found the kernel's PDB in the dump
# but no ISF matches (2.28.2): the GUID (32 hex digits) followed by the age in decimal. Only the x64
# kernel's name is taken: the symbol file Tartarus makes is for that one.
MISSING_SYMBOLS_LINE = re.compile(
    r"The symbols can be downloaded later using pdbconv\.py "
    r"-p ntkrnlmp\.pdb -g ([0-9A-Fa-f]{32})([0-9]{1,10})\b"
)
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
class MissingSymbols:
    """The kernel PDB id a dump needs a symbol file for."""

    guid: str
    age: int

    def to_json(self) -> dict[str, str | int]:
        return {"guid": self.guid, "age": self.age}


@dataclass(frozen=True)
class PluginRun:
    """`rows` is None exactly when `error` is set; `missing_symbols` only when it is NO_SYMBOLS."""

    rows: list[dict] | None
    seconds: float
    error: str | None
    version: str | None = None
    missing_symbols: MissingSymbols | None = None


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

    def command(self, plugin: str, pids: Sequence[int] = (), *, verbose: bool = False) -> list[str]:
        # --offline: the cape container has internet access, and without it a missing ISF would
        # make Volatility fetch the kernel's PDB from Microsoft on its own.
        command = [
            VOLATILITY_COMMAND,
            "-q",
            *(["-v"] if verbose else []),
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

    def run(
        self, plugin: str, timeout: float, pids: Sequence[int] = (), *, verbose: bool = False
    ) -> PluginRun:
        """`verbose` asks for the INFO log, which names the kernel if symbols are missing."""
        started = self.clock()
        try:
            result = self.runner(self.command(plugin, pids, verbose=verbose), timeout)
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
        missing = _missing_symbols_of(result) if error == NO_SYMBOLS else None
        return PluginRun(rows, seconds, error, version, missing)


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
    return exit_message(result)


def exit_message(result: CommandResult) -> str:
    """The exit status of a Volatility process and the last line it wrote to stderr."""
    message = f"volatility exited with status {result.returncode}"
    lines = [line.strip() for line in result.stderr.splitlines() if line.strip()]
    return f"{message}: {lines[-1][:ERROR_DETAIL_LIMIT]}" if lines else message


def _missing_symbols_of(result: CommandResult) -> MissingSymbols | None:
    found = MISSING_SYMBOLS_LINE.search(result.stderr + result.stdout)
    return MissingSymbols(found.group(1).upper(), int(found.group(2))) if found else None


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
