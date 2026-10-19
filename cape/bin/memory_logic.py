"""Runs Volatility3 on an analysis's memory dump and writes what it found next to the dump.

The dump (`storage/analyses/<id>/memory.dmp`, 4 GiB for a 4 GiB guest) is writable only inside the
`cape` container; the backend sees the storage read-only. So this module, used by `guest-control`,
runs `vol` here, as the unprivileged `cape` user, and leaves its JSON in
`storage/analyses/<id>/memory/` for the backend to read, and deletes the dump once the backend
has what it needs. Volatility's own command line lives in `volatility.py`.
"""

import json
import os
import shutil
import threading
import time
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from finish_logic import TASK_ID_NOT_DIGITS, parse_task_id
from volatility import PluginRun, Runner, Volatility, VolatilityUnavailableError, run_command

STORAGE_DIRECTORY = Path("/opt/CAPEv2/storage")
# On the `guest-images` volume next to the guest registry, so it survives `docker compose down`;
# Volatility looks for ISF files in its `windows/` subdirectory.
SYMBOLS_DIRECTORY = Path("/var/lib/libvirt/tartarus/symbols")
PLUGIN_TIMEOUT_SECONDS = 120.0
OVERALL_TIMEOUT_SECONDS = 300.0
ANALYSIS_FILE_MODE = 0o644
ANALYSIS_DIRECTORY_MODE = 0o755

CAPE_USER = "cape"
# All that `vol` gets: the service's own environment holds the bearer token. HOME is where
# Volatility keeps its identifier cache.
CAPE_ENVIRONMENT = {"HOME": "/home/cape", "PATH": "/usr/local/bin:/usr/bin:/bin", "LANG": "C.UTF-8"}

PROBE_PLUGIN = "windows.info"
CONTEXT_PLUGINS = ("windows.pslist", "windows.cmdline")
PER_PROCESS_PLUGINS = ("windows.malware.malfind", "windows.malware.hollowprocesses")
NO_PROCESSES = "the report names no process of the analysis"
DUMP_MISSING = {"error": "no memory dump for this task"}
RUNNING = {"error": "this task's memory dump is being analysed"}

type Answer = tuple[int, dict[str, Any] | None]


class DumpMissingError(Exception):
    """The analysis has no regular `memory.dmp`."""


class AlreadyRunningError(Exception):
    """Another analyse of the same task is reading the dump."""


class ResultsNotWrittenError(Exception):
    """The `memory/` folder could not be written; the message says why, without a path."""


@dataclass(frozen=True)
class Holder:
    pid: int
    name: str


@dataclass(frozen=True)
class Scan:
    version: str | None
    symbols: str | None
    pids: list[int]
    runs: dict[str, PluginRun]
    skipped: dict[str, str]


def in_container(log: Callable[[str], None]) -> "MemoryAnalyser":
    runner = partial(run_command, user=CAPE_USER, environment=CAPE_ENVIRONMENT)
    return MemoryAnalyser(STORAGE_DIRECTORY, SYMBOLS_DIRECTORY, runner, log=log)


def pids_from_report(report: Path) -> list[int]:
    """The analysis's own processes, so the plugins that cost seconds per process scan only those.

    A report that cannot be read or has no processes gives none: the cheap plugins still run.
    """
    try:
        processes = json.loads(report.read_text())["behavior"]["processes"]
        pids = {entry["process_id"] for entry in processes}
    except (OSError, ValueError, KeyError, TypeError):
        return []
    return sorted(pid for pid in pids if _is_pid(pid))


def _is_pid(value: object) -> bool:
    # bool is an int subclass, and a negative id is not a pid.
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def symbols_file(info_rows: Sequence[dict]) -> str | None:
    """The ISF file `windows.info` says it used, by name."""
    for row in info_rows:
        if row.get("Variable") == "Symbols" and isinstance(row.get("Value"), str):
            return Path(unquote(urlparse(row["Value"]).path)).name or None
    return None


class MemoryAnalyser:
    def __init__(
        self,
        storage: Path,
        symbols_directory: Path,
        runner: Runner,
        log: Callable[[str], None],
    ) -> None:
        self.storage = storage
        self.symbols_directory = symbols_directory
        self.runner = runner
        self.log = log
        self.clock: Callable[[], float] = time.monotonic
        self.plugin_timeout = PLUGIN_TIMEOUT_SECONDS
        self.overall_timeout = OVERALL_TIMEOUT_SECONDS
        self.proc_directory = Path("/proc")
        self._running: set[int] = set()
        self._running_lock = threading.Lock()

    def analyse(self, task_id: int) -> dict[str, Any]:
        with self._claimed(task_id):
            dump = self._dump_of(task_id)
            started = self.clock()
            volatility = Volatility(dump, self.symbols_directory, self.runner, self.clock)
            pids = pids_from_report(self._analysis(task_id) / "reports" / "report.json")
            scan = self._scan(volatility, pids)
            self._write(task_id, scan, dump_bytes=dump.stat().st_size)
            return _summary(scan, seconds=self.clock() - started)

    def delete_dump(self, task_id: int) -> list[Holder]:
        """Removes the dump; returns the processes that still hold it open, which keep its space."""
        with self._claimed(task_id):
            dump = self._dump_of(task_id)
            real_path = os.path.realpath(dump)
            dump.unlink()
        holders = self._holders_of_deleted(real_path)
        for holder in holders:
            self.log(
                f"the memory dump of task {task_id} is deleted but still open by {holder.name}"
                f" (pid {holder.pid}); its disk space is not freed until that process closes it"
            )
        return holders

    def _analysis(self, task_id: int) -> Path:
        return self.storage / "analyses" / str(task_id)

    def _dump_of(self, task_id: int) -> Path:
        dump = self._analysis(task_id) / "memory.dmp"
        if dump.is_symlink() or not dump.is_file():
            raise DumpMissingError
        return dump

    @contextmanager
    def _claimed(self, task_id: int) -> Iterator[None]:
        with self._running_lock:
            if task_id in self._running:
                raise AlreadyRunningError
            self._running.add(task_id)
        try:
            yield
        finally:
            with self._running_lock:
                self._running.discard(task_id)

    def _scan(self, volatility: Volatility, pids: list[int]) -> Scan:
        deadline = self.clock() + self.overall_timeout
        probe = self._run(volatility, PROBE_PLUGIN, deadline)
        plugins = (*CONTEXT_PLUGINS, *PER_PROCESS_PLUGINS)
        if probe.error:
            failed = PluginRun(None, 0.0, probe.error)
            return Scan(probe.version, None, pids, dict.fromkeys(plugins, failed), {})
        runs: dict[str, PluginRun] = {}
        skipped: dict[str, str] = {}
        for plugin in plugins:
            if plugin in PER_PROCESS_PLUGINS and not pids:
                skipped[plugin] = NO_PROCESSES
            else:
                limited_to = pids if plugin in PER_PROCESS_PLUGINS else ()
                runs[plugin] = self._run(volatility, plugin, deadline, limited_to)
        return Scan(probe.version, symbols_file(probe.rows or []), pids, runs, skipped)

    def _run(
        self, volatility: Volatility, plugin: str, deadline: float, pids: Sequence[int] = ()
    ) -> PluginRun:
        remaining = deadline - self.clock()
        if remaining <= 0:
            return PluginRun(
                None, 0.0, f"the overall time limit of {self.overall_timeout:g} s was reached"
            )
        return volatility.run(plugin, min(self.plugin_timeout, remaining), pids)

    def _write(self, task_id: int, scan: Scan, dump_bytes: int) -> None:
        folder = self._analysis(task_id) / "memory"
        try:
            # A rerun must not leave the file of a plugin that fails this time.
            shutil.rmtree(folder, ignore_errors=True)
            folder.mkdir()
            folder.chmod(ANALYSIS_DIRECTORY_MODE)
            for plugin, run in scan.runs.items():
                if run.rows is not None:
                    _write_readable(folder / f"{plugin}.json", run.rows)
            for plugin in scan.skipped:
                _write_readable(folder / f"{plugin}.json", [])
            _write_readable(folder / "run.json.tmp", _run_json(scan, dump_bytes))
            # Last, and atomically: the backend treats the presence of run.json as "finished".
            os.replace(folder / "run.json.tmp", folder / "run.json")
        except OSError as unwritable:
            raise ResultsNotWrittenError(
                f"the results could not be written ({type(unwritable).__name__})"
            ) from unwritable

    def _holders_of_deleted(self, real_path: str) -> list[Holder]:
        return [
            Holder(int(process.name), _name_of(process))
            for process in sorted(self.proc_directory.glob("[0-9]*"))
            if _holds_deleted(process, real_path)
        ]


def _holds_deleted(process: Path, real_path: str) -> bool:
    deleted_link = f"{real_path} (deleted)"
    try:
        descriptors = (process / "fd").iterdir()
        return any(os.readlink(descriptor) == deleted_link for descriptor in descriptors)
    except OSError:
        return False


def _name_of(process: Path) -> str:
    try:
        return (process / "comm").read_text().strip() or "?"
    except OSError:
        return "?"


def _write_readable(path: Path, content: Any) -> None:
    path.write_text(json.dumps(content))
    path.chmod(ANALYSIS_FILE_MODE)


def _plugin_entries(scan: Scan) -> dict[str, dict[str, Any]]:
    entries: dict[str, dict[str, Any]] = {
        plugin: {"rows": len(run.rows or []), "seconds": run.seconds, "error": run.error}
        for plugin, run in scan.runs.items()
    }
    for plugin, reason in scan.skipped.items():
        entries[plugin] = {"rows": 0, "seconds": 0.0, "error": None, "skipped": reason}
    return entries


def _run_json(scan: Scan, dump_bytes: int) -> dict[str, Any]:
    return {
        "volatility": scan.version,
        "dump_bytes": dump_bytes,
        "pids": scan.pids,
        "plugins": _plugin_entries(scan),
        "symbols": scan.symbols,
    }


def _summary(scan: Scan, seconds: float) -> dict[str, Any]:
    entries = _plugin_entries(scan)
    return {
        "plugins": {plugin: entry["rows"] for plugin, entry in entries.items()},
        "errors": {plugin: entry["error"] for plugin, entry in entries.items() if entry["error"]},
        "seconds": seconds,
        "pids": scan.pids,
    }


def analyse_response(raw_task_id: str, analyser: MemoryAnalyser) -> Answer:
    task_id = parse_task_id(raw_task_id)
    if task_id is None:
        return 400, TASK_ID_NOT_DIGITS
    try:
        return 200, analyser.analyse(task_id)
    except DumpMissingError:
        return 404, DUMP_MISSING
    except AlreadyRunningError:
        return 409, RUNNING
    except VolatilityUnavailableError as unavailable:
        return 502, {"error": str(unavailable)}
    except ResultsNotWrittenError as unwritten:
        return 500, {"error": str(unwritten)}


def delete_dump_response(raw_task_id: str, analyser: MemoryAnalyser) -> Answer:
    task_id = parse_task_id(raw_task_id)
    if task_id is None:
        return 400, TASK_ID_NOT_DIGITS
    try:
        analyser.delete_dump(task_id)
    except DumpMissingError:
        return 404, DUMP_MISSING
    except AlreadyRunningError:
        return 409, RUNNING
    return 204, None
