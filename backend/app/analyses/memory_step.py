"""The memory step of an analysis: Volatility3 on its dump before the ingest, the dump's removal
after it. Neither can fail the analysis: what happens is recorded in `summary.memory`.
"""

import logging
from collections.abc import Mapping
from http import HTTPStatus
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from app.analyses.memory import MemoryFindings, MemorySummary
from app.analyses.memory_disk import CAPE_FREESPACE_FLOOR_MB
from app.analyses.ports import MemoryControl
from app.db.models import Analysis
from app.guest.errors import GuestControlRejected
from app.guest.schemas import MemoryAnalysis

logger = logging.getLogger(__name__)

DUMP_FILE = "memory.dmp"
NO_DUMP_REASON = (
    "CAPE took no memory dump: it skips the dump when the storage has less than "
    f"{CAPE_FREESPACE_FLOOR_MB} MB free"
)
NO_REASON = "the memory step failed without saying why"


class MemoryStep:
    def __init__(self, control: MemoryControl, cape_storage_path: Path) -> None:
        self._control = control
        self._storage = cape_storage_path

    async def run(self, analysis: Analysis, task_id: int) -> MemorySummary | None:
        """Reads the dump with Volatility3; None when the analysis asked for none.

        A re-ingest gets back what the first run recorded, and does not read the dump again.
        """
        if analysis.options.get("memory_dump") is not True:
            return None
        recorded = _recorded(analysis)
        if recorded is not None:
            return recorded
        dump_bytes = self._dump_size(task_id)
        try:
            analysed = await self._control.analyse_memory(task_id)
        except GuestControlRejected as rejected:
            if rejected.status == HTTPStatus.NOT_FOUND:
                return MemorySummary(
                    dump_taken=False, findings=MemoryFindings.UNAVAILABLE, error=NO_DUMP_REASON
                )
            return _failed(dump_bytes, rejected.message)
        except Exception as error:  # noqa: BLE001 - nothing here may fail the analysis
            logger.warning("Reading the memory dump of task %s failed: %s", task_id, error)
            return _failed(dump_bytes, str(error) or type(error).__name__)
        return _read_from(analysed, dump_bytes)

    async def release(
        self, analysis: Analysis, task_id: int, memory: MemorySummary | None
    ) -> MemorySummary | None:
        """Deletes the dump once its events are indexed, unless the analyst asked to keep it."""
        if memory is None or _keeps_the_dump(analysis, memory):
            return memory
        return memory.model_copy(update={"dump_deleted": await self._delete(task_id)})

    async def _delete(self, task_id: int) -> bool:
        try:
            await self._control.delete_memory_dump(task_id)
        except GuestControlRejected as rejected:
            return rejected.status == HTTPStatus.NOT_FOUND
        except Exception as error:  # noqa: BLE001 - nothing here may fail the analysis
            logger.warning("Deleting the memory dump of task %s failed: %s", task_id, error)
            return False
        return True

    def _dump_size(self, task_id: int) -> int | None:
        try:
            return (self._storage / "analyses" / str(task_id) / DUMP_FILE).stat().st_size
        except OSError:
            return None


def _recorded(analysis: Analysis) -> MemorySummary | None:
    summary: Mapping[str, Any] = analysis.summary or {}
    try:
        return MemorySummary.model_validate(summary["memory"])
    except (KeyError, ValidationError):
        return None


def _keeps_the_dump(analysis: Analysis, memory: MemorySummary) -> bool:
    return (
        analysis.options.get("keep_memory_dump") is True
        or not memory.dump_taken
        or memory.dump_deleted is True
    )


def _failed(dump_bytes: int | None, error: str) -> MemorySummary:
    return MemorySummary(
        dump_taken=dump_bytes is not None,
        findings=MemoryFindings.FAILED,
        error=error or NO_REASON,
        dump_bytes=dump_bytes,
    )


def _read_from(analysed: MemoryAnalysis, dump_bytes: int | None) -> MemorySummary:
    every_plugin_failed = bool(analysed.plugins) and set(analysed.errors) >= set(analysed.plugins)
    return MemorySummary(
        dump_taken=True,
        findings=MemoryFindings.FAILED if every_plugin_failed else MemoryFindings.OK,
        error="; ".join(f"{plugin}: {text}" for plugin, text in sorted(analysed.errors.items()))
        or None,
        dump_bytes=dump_bytes,
    )
