"""The runner's path for an imported packet capture: CAPE's own `pcap` task does the network
processing, with no guest and no machine (docs/plans/m9-spikes/P1-findings.md).
"""

import asyncio
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Protocol

from app.db.models import Analysis
from app.imports.packet_capture import UnreadableCaptureError, first_packet_time
from app.imports.upload import import_file, recorded_import_kind

PCAP_KIND = "pcap"


class ImportRefusedError(Exception):
    """The imported file cannot be sent on; the message says why."""


@dataclass(frozen=True)
class Submitted:
    """A task CAPE accepted. `started_at` is set when the analysis's own clock is not CAPE's."""

    task_id: int
    started_at: datetime | None = None


class PcapTaskApi(Protocol):
    async def create_pcap_task(self, source: Path, filename: str) -> int: ...


async def submit_import(cape: PcapTaskApi, analysis: Analysis, imports_dir: Path) -> Submitted:
    """Raises `ImportRefusedError` for a file or a kind that cannot be imported, and `CapeError`
    when CAPE refuses the task.
    """
    kind = recorded_import_kind(analysis.options)
    if kind != PCAP_KIND:
        raise ImportRefusedError(f"Importing a {kind} is not supported")
    return await _submit_pcap(cape, analysis, import_file(imports_dir, analysis.id))


async def _submit_pcap(cape: PcapTaskApi, analysis: Analysis, stored: Path) -> Submitted:
    # CAPE stamps a `pcap` task with the moment of the import; the events must keep the
    # capture's own time.
    try:
        started_at = await asyncio.to_thread(first_packet_time, stored)
    except FileNotFoundError:
        raise ImportRefusedError(
            "The uploaded file is missing, so it cannot be sent to CAPE"
        ) from None
    except UnreadableCaptureError as unreadable:
        raise ImportRefusedError(str(unreadable)) from None
    task_id = await cape.create_pcap_task(stored, analysis.filename)
    return Submitted(task_id, started_at)
