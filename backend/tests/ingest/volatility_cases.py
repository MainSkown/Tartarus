import json
import shutil
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.ingest.protocol import IngestContext
from tests.ingest.reports import call, process, report_of

FIXTURES = Path(__file__).parent.parent / "fixtures" / "volatility"
P9_FIXTURES = Path(__file__).resolve().parents[3] / "docs" / "history" / "m9-spikes" / "fixtures"
ANALYSIS_ID = 41
STARTED = datetime(2026, 10, 18, 22, 15, 0, tzinfo=UTC)
ENDED = "2026-10-18 22:16:10"

MALFIND = "windows.malware.malfind"
HOLLOWPROCESSES = "windows.malware.hollowprocesses"
PSLIST = "windows.pslist"
CMDLINE = "windows.cmdline"

SAMPLE_PID = 1936
HOLLOWED_PID = 6304
INJECTED_PID = 1384
DEFENDER_PID = 3172
SAMPLE_PIDS = (SAMPLE_PID, HOLLOWED_PID, INJECTED_PID)
INJECTED_ADDRESS = "0x1bccc4e0000"
HOLLOWED_ADDRESS = "0x140000000"
CAPEMON_PAGES = ("0x7ffbbf7c0000", "0x7ffbc09c0000", "0x7ffbc0bd0000")


def read_fixture(plugin: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = json.loads((FIXTURES / f"{plugin}.json").read_text())
    return rows


def rows_of_pids(plugin: str, pids: Iterable[int]) -> list[dict[str, Any]]:
    """What the producer's `--pid` leaves of a whole-dump output."""
    wanted = set(pids)
    return [row for row in read_fixture(plugin) if row["PID"] in wanted]


def run_json(plugins: Mapping[str, Any], pids: Iterable[int] = SAMPLE_PIDS) -> dict[str, Any]:
    return {
        "volatility": "2.28.2",
        "dump_bytes": 4294776995,
        "pids": list(pids),
        "plugins": dict(plugins),
        "symbols": "ntkrnlmp.pdb/24DE61DB3A27C5B383DFF181CB51F7E1-1",
    }


def plugin_entry(rows: int, error: str | None = None) -> dict[str, Any]:
    return {"rows": rows, "seconds": 0.8, "error": error}


def write_memory(
    root: Path, outputs: Mapping[str, Any], *, entries: Mapping[str, Any] | None = None
) -> Path:
    """The producer's folder: one `<plugin>.json` per output and a `run.json` describing them."""
    memory = root / "memory"
    memory.mkdir(parents=True, exist_ok=True)
    for plugin, rows in outputs.items():
        (memory / f"{plugin}.json").write_text(json.dumps(rows))
    described = {plugin: plugin_entry(len(rows)) for plugin, rows in outputs.items()}
    (memory / "run.json").write_text(json.dumps(run_json(entries or described)))
    return root


def write_fixture_memory(
    root: Path, *plugins: str, malfind_pids: Iterable[int] | None = None
) -> Path:
    """Copies the real plugin outputs; `malfind_pids` narrows malfind the way `--pid` does."""
    outputs: dict[str, Any] = {}
    for plugin in plugins:
        outputs[plugin] = (
            rows_of_pids(plugin, malfind_pids)
            if plugin == MALFIND and malfind_pids is not None
            else read_fixture(plugin)
        )
    return write_memory(root, outputs)


def copy_fixture_file(root: Path, plugin: str) -> None:
    (root / "memory").mkdir(parents=True, exist_ok=True)
    shutil.copyfile(FIXTURES / f"{plugin}.json", root / "memory" / f"{plugin}.json")


def context_of(analysis_dir: Path | None) -> IngestContext:
    return IngestContext(analysis_id=ANALYSIS_ID, started_at=STARTED, analysis_dir=analysis_dir)


def sample_report(*, ended: str | None = ENDED) -> dict[str, Any]:
    """Capemon monitored the sample and its two pings; its guest clock is two hours behind."""
    monitored = [
        {**process(pid, [call("NtClose")], name=name), "first_seen": "2026-10-18 20:15:03"}
        for pid, name in (
            (SAMPLE_PID, "memtest3.exe"),
            (HOLLOWED_PID, "PING.EXE"),
            (INJECTED_PID, "PING.EXE"),
        )
    ]
    info: dict[str, Any] = {"started": "2026-10-18 22:15:00"}
    if ended is not None:
        info["ended"] = ended
    return {**report_of(*monitored), "info": info}


def malfind_row(pid: int, start: int, hexdump: str, **columns: Any) -> dict[str, Any]:
    """A malfind row; keyword arguments override its columns (`Notes`, `Protection`, `Process`)."""
    return {
        "PID": pid,
        "Process": "notepad.exe",
        "Start VPN": start,
        "End VPN": start + 0xFFF,
        "Protection": "PAGE_EXECUTE_READWRITE",
        "Tag": "VadS",
        "PrivateMemory": 1,
        "CommitCharge": 1,
        "Notes": None,
        "Hexdump": hexdump,
        "Disasm": "",
        "File output": "Disabled",
        "__children": [],
        **columns,
    }


def hexdump_of(first: bytes) -> str:
    return " ".join(f"{byte:02x}" for byte in first.ljust(64, b"\x00"))


P9_IMAGE_PLUGINS = {
    PSLIST: "vol3-2.28.2-windows.pslist.p9.json",
    MALFIND: "vol3-2.28.2-windows.malware.malfind.all-pids.json",
}
P9_INJECTED_PID = 3888


def write_p9_image_memory(analysis_dir: Path) -> Path:
    """What the control service leaves for the P2 image, scanned whole (no pids)."""
    outputs = {
        plugin: json.loads((P9_FIXTURES / name).read_text())
        for plugin, name in P9_IMAGE_PLUGINS.items()
    }
    return write_memory(analysis_dir, outputs)
