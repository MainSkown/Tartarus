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
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from finish_logic import TASK_ID_NOT_DIGITS, parse_task_id
from volatility import (
    CAPE_ENVIRONMENT,
    CAPE_USER,
    NO_SYMBOLS,
    NOT_A_MEMORY_IMAGE,
    SYMBOLS_DIRECTORY,
    MissingSymbols,
    PluginRun,
    Runner,
    Volatility,
    VolatilityUnavailableError,
    run_command,
)

STORAGE_DIRECTORY = Path("/opt/CAPEv2/storage")
IMPORTS_DIRECTORY = Path("/imports")
PLUGIN_TIMEOUT_SECONDS = 120.0
OVERALL_TIMEOUT_SECONDS = 300.0
ANALYSIS_FILE_MODE = 0o644
ANALYSIS_DIRECTORY_MODE = 0o755

PROBE_PLUGIN = "windows.info"
CONTEXT_PLUGINS = ("windows.pslist", "windows.cmdline")
PER_PROCESS_PLUGINS = ("windows.malware.malfind", "windows.malware.hollowprocesses")
DUMP_MISSING = {"error": "no memory dump for this task"}
IMAGE_REJECTED = {"error": "the image must be a file under /imports"}
IMAGE_MISSING = {"error": "no such image under /imports"}
RUNNING = {"error": "this task's memory dump is being analysed"}
NOT_AN_IMAGE_TASK = {"error": "only the findings of an imported memory image can be deleted here"}
# CAPE's own task ids are small; the backend gives an imported image's findings a task id from here
# up (backend/app/analyses/memory_import.py), so this route can never touch a real task's folder.
IMAGE_TASK_ID_BASE = 900_000_000

type Answer = tuple[int, dict[str, Any] | None]


class DumpMissingError(Exception):
    """The analysis has no regular `memory.dmp`."""


class ImageRejectedError(Exception):
    """The requested image path leads outside the imports folder."""


class ImageMissingError(Exception):
    """The requested image is not a regular file inside the imports folder, symlinks included."""


class NotAnImageTaskError(Exception):
    """The task id is a CAPE task's, not an imported image's."""


class AlreadyRunningError(Exception):
    """Another analyse of the same task is reading the dump."""


class ResultsNotWrittenError(Exception):
    """The `memory/` folder could not be written; the message says why, without a path."""


REFUSALS: dict[type[Exception], Answer] = {
    DumpMissingError: (404, DUMP_MISSING),
    ImageRejectedError: (400, IMAGE_REJECTED),
    ImageMissingError: (404, IMAGE_MISSING),
    AlreadyRunningError: (409, RUNNING),
    NotAnImageTaskError: (400, NOT_AN_IMAGE_TASK),
}


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
    missing_symbols: MissingSymbols | None = None


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
        self.imports_directory = IMPORTS_DIRECTORY
        self._running: set[int] = set()
        self._running_lock = threading.Lock()

    def analyse(self, task_id: int, image: str | None = None) -> dict[str, Any]:
        """Scans the task's dump, or `image` (a file under the imports folder) when one is named.

        Results go to the task's `memory/` folder either way. An image has no report, so it is
        scanned whole.
        """
        with self._claimed(task_id):
            if image is None:
                dump = self._dump_of(task_id)
                pids = pids_from_report(self._analysis(task_id) / "reports" / "report.json")
            else:
                dump = self._image_in_imports(image)
                pids = []
            started = self.clock()
            volatility = Volatility(dump, self.symbols_directory, self.runner, self.clock)
            scan = self._scan(volatility, pids, standalone_image=image is not None)
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

    def delete_image_findings(self, task_id: int) -> None:
        """Removes the task folder an imported image's scan wrote; nothing to remove is fine."""
        if task_id < IMAGE_TASK_ID_BASE:
            raise NotAnImageTaskError
        with self._claimed(task_id):
            shutil.rmtree(self._analysis(task_id), ignore_errors=True)

    def _analysis(self, task_id: int) -> Path:
        return self.storage / "analyses" / str(task_id)

    def _dump_of(self, task_id: int) -> Path:
        dump = self._analysis(task_id) / "memory.dmp"
        if dump.is_symlink() or not dump.is_file():
            raise DumpMissingError
        return dump

    def _image_in_imports(self, image: str) -> Path:
        root = self.imports_directory
        # Lexical first, so `..` cannot leave the folder; the symlink check below handles the rest.
        candidate = Path(os.path.normpath(root / image))
        if root not in candidate.parents:
            raise ImageRejectedError
        through_no_symlink = Path(os.path.realpath(root)) / candidate.relative_to(root)
        if candidate.resolve() != through_no_symlink or not candidate.is_file():
            raise ImageMissingError
        return candidate

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

    def _scan(self, volatility: Volatility, pids: list[int], *, standalone_image: bool) -> Scan:
        deadline = self.clock() + self.overall_timeout
        probe = self._run(volatility, PROBE_PLUGIN, deadline, verbose=True)
        if probe.error:
            failed = PluginRun(None, 0.0, _probe_error(probe, standalone_image))
            runs = dict.fromkeys((*CONTEXT_PLUGINS, *PER_PROCESS_PLUGINS), failed)
            return Scan(probe.version, None, pids, runs, probe.missing_symbols)
        runs = {plugin: self._run(volatility, plugin, deadline) for plugin in CONTEXT_PLUGINS}
        runs |= self._per_process_runs(volatility, pids, deadline)
        return Scan(probe.version, symbols_file(probe.rows or []), pids, runs)

    def _per_process_runs(
        self, volatility: Volatility, pids: list[int], deadline: float
    ) -> dict[str, PluginRun]:
        if pids:
            return {
                plugin: self._run(volatility, plugin, deadline, pids)
                for plugin in PER_PROCESS_PLUGINS
            }
        # Without pids each plugin walks every process: 129 s one after the other, 66 s together
        # on a 4 GB image (P2), against the 300 s overall limit.
        with ThreadPoolExecutor(max_workers=len(PER_PROCESS_PLUGINS)) as pool:
            pending = {
                plugin: pool.submit(self._run, volatility, plugin, deadline)
                for plugin in PER_PROCESS_PLUGINS
            }
            return {plugin: future.result() for plugin, future in pending.items()}

    def _run(
        self,
        volatility: Volatility,
        plugin: str,
        deadline: float,
        pids: Sequence[int] = (),
        *,
        verbose: bool = False,
    ) -> PluginRun:
        remaining = deadline - self.clock()
        if remaining <= 0:
            return PluginRun(
                None, 0.0, f"the overall time limit of {self.overall_timeout:g} s was reached"
            )
        return volatility.run(plugin, min(self.plugin_timeout, remaining), pids, verbose=verbose)

    def _write(self, task_id: int, scan: Scan, dump_bytes: int) -> None:
        folder = self._analysis(task_id) / "memory"
        try:
            self._ensure_analysis_directory(task_id)
            # A rerun must not leave the file of a plugin that fails this time.
            shutil.rmtree(folder, ignore_errors=True)
            folder.mkdir()
            folder.chmod(ANALYSIS_DIRECTORY_MODE)
            for plugin, run in scan.runs.items():
                if run.rows is not None:
                    _write_readable(folder / f"{plugin}.json", run.rows)
            _write_readable(folder / "run.json.tmp", _run_json(scan, dump_bytes))
            # The service runs as root; CAPE, as `cape`, deletes the whole task folder with the
            # analysis and cannot remove what root leaves in it.
            _give_to_owner_of(self._analysis(task_id), [folder, *folder.iterdir()])
            # Last, and atomically: the backend treats the presence of run.json as "finished".
            os.replace(folder / "run.json.tmp", folder / "run.json")
        except OSError as unwritable:
            raise ResultsNotWrittenError(
                f"the results could not be written ({type(unwritable).__name__})"
            ) from unwritable

    def _ensure_analysis_directory(self, task_id: int) -> None:
        analysis = self._analysis(task_id)
        if not analysis.exists():
            analysis.mkdir(parents=True)
            analysis.chmod(ANALYSIS_DIRECTORY_MODE)

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


def _give_to_owner_of(analysis: Path, paths: Sequence[Path]) -> None:
    owner = analysis.stat()
    for path in paths:
        os.chown(path, owner.st_uid, owner.st_gid)


def _write_readable(path: Path, content: Any) -> None:
    path.write_text(json.dumps(content))
    path.chmod(ANALYSIS_FILE_MODE)


def _plugin_entries(scan: Scan) -> dict[str, dict[str, Any]]:
    return {
        plugin: {"rows": len(run.rows or []), "seconds": run.seconds, "error": run.error}
        for plugin, run in scan.runs.items()
    }


def _probe_error(probe: PluginRun, standalone_image: bool) -> str | None:
    # `vol -v` names the kernel's PDB whenever it found a kernel and only the ISF is missing. A
    # CAPE task's dump is a Windows guest by construction, so only a named file can be garbage.
    if standalone_image and probe.error == NO_SYMBOLS and probe.missing_symbols is None:
        return NOT_A_MEMORY_IMAGE
    return probe.error


def _missing_symbols_entry(scan: Scan) -> dict[str, Any]:
    return {"missing_symbols": scan.missing_symbols.to_json()} if scan.missing_symbols else {}


def _run_json(scan: Scan, dump_bytes: int) -> dict[str, Any]:
    return {
        "volatility": scan.version,
        "dump_bytes": dump_bytes,
        "pids": scan.pids,
        "plugins": _plugin_entries(scan),
        "symbols": scan.symbols,
        **_missing_symbols_entry(scan),
    }


def _summary(scan: Scan, seconds: float) -> dict[str, Any]:
    entries = _plugin_entries(scan)
    return {
        "plugins": {plugin: entry["rows"] for plugin, entry in entries.items()},
        "errors": {plugin: entry["error"] for plugin, entry in entries.items() if entry["error"]},
        "seconds": seconds,
        "pids": scan.pids,
        **_missing_symbols_entry(scan),
    }


def analyse_response(
    raw_task_id: str, analyser: MemoryAnalyser, image: str | None = None
) -> Answer:
    task_id = parse_task_id(raw_task_id)
    if task_id is None:
        return 400, TASK_ID_NOT_DIGITS
    try:
        return 200, analyser.analyse(task_id, image)
    except (
        DumpMissingError,
        ImageRejectedError,
        ImageMissingError,
        AlreadyRunningError,
    ) as refused:
        return REFUSALS[type(refused)]
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


def delete_findings_response(raw_task_id: str, analyser: MemoryAnalyser) -> Answer:
    task_id = parse_task_id(raw_task_id)
    if task_id is None:
        return 400, TASK_ID_NOT_DIGITS
    try:
        analyser.delete_image_findings(task_id)
    except (NotAnImageTaskError, AlreadyRunningError) as refused:
        return REFUSALS[type(refused)]
    return 204, None
