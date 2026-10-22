"""Reads the folder the memory step leaves beside `report.json`: `memory/run.json` and one
`<plugin>.json` per plugin, each a JSON array of the rows Volatility3 printed with `-r json`.

Every reader tolerates what a half-written or hostile folder can hold: it returns nothing for the
part it cannot read and leaves the other parts alone.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.ingest.json_file import load_json_file
from app.ingest.reading import mapping_list, text_or_none, to_int

MAX_PLUGIN_OUTPUT_BYTES = 512 * 1024**2
MEMORY_FOLDER = "memory"
RUN_FILE = "run.json"
PSLIST = "windows.pslist"
CMDLINE = "windows.cmdline"


def memory_folder(analysis_dir: Path | None) -> Path | None:
    return None if analysis_dir is None else analysis_dir / MEMORY_FOLDER


def read_run(folder: Path) -> Mapping[str, Any] | None:
    """`run.json`, or None when there is none: no memory step ran. One that cannot be read
    still counts as present, because the plugin files beside it are not made unusable by it.
    """
    path = folder / RUN_FILE
    if not path.is_file():
        return None
    document = _load(path)
    return document if isinstance(document, Mapping) else {}


def read_rows(folder: Path, run: Mapping[str, Any], plugin: str) -> list[Any]:
    """The rows of a plugin's output; none when it failed, left no file or wrote no array."""
    if _failed(run, plugin):
        return []
    rows = _load(folder / f"{plugin}.json")
    return rows if isinstance(rows, list) else []


def _failed(run: Mapping[str, Any], plugin: str) -> bool:
    plugins = run.get("plugins")
    entry = plugins.get(plugin) if isinstance(plugins, Mapping) else None
    return isinstance(entry, Mapping) and bool(entry.get("error"))


def _load(path: Path) -> object:
    try:
        return load_json_file(path, MAX_PLUGIN_OUTPUT_BYTES)
    except (OSError, ValueError):
        return None


@dataclass(frozen=True)
class ProcessTable:
    """What `windows.pslist` and `windows.cmdline` say of each pid: context, never events."""

    names: Mapping[int, str]
    command_lines: Mapping[int, str]

    @classmethod
    def read(cls, folder: Path, run: Mapping[str, Any]) -> "ProcessTable":
        return cls(
            _by_pid(read_rows(folder, run, PSLIST), "ImageFileName"),
            _by_pid(read_rows(folder, run, CMDLINE), "Args"),
        )


def _by_pid(rows: list[Any], column: str) -> dict[int, str]:
    by_pid: dict[int, str] = {}
    for row in mapping_list(rows):
        pid, text = to_int(row.get("PID")), text_or_none(row.get(column))
        if pid is not None and text is not None:
            by_pid.setdefault(pid, text.strip())
    return by_pid
