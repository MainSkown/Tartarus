"""The runner's path for an imported memory image: the control service's Volatility3 reads the
upload in place, with no guest and no CAPE task (docs/plans/m9-spikes/P2-findings.md).

The findings land where a run's do, in `<cape storage>/analyses/<task id>/memory/`; an image has
no task, so it gets an id CAPE will never hand out.
"""

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from app.analyses.memory import MemoryFindings, MemorySummary
from app.analyses.memory_step import summarise_analysis
from app.analyses.ports import EventIngester, IngestResult, MemoryControl
from app.guest.errors import GuestControlError, GuestControlRejected
from app.guest.schemas import MemoryAnalysis, MissingSymbols
from app.imports.upload import UPLOAD_NAME, import_file

# CAPE's own task ids are small; the control service takes any run of digits.
IMAGE_TASK_ID_BASE = 900_000_000


class MemoryImportFailedError(Exception):
    """The image cannot be turned into findings; the message says why, for the analyst."""


@dataclass(frozen=True)
class ImportedImage:
    indexed: IngestResult
    memory: MemorySummary


def image_task_id(analysis_id: int) -> int:
    return IMAGE_TASK_ID_BASE + analysis_id


class MemoryImport:
    def __init__(
        self,
        control: MemoryControl,
        ingester: EventIngester,
        cape_storage_path: Path,
        imports_dir: Path,
    ) -> None:
        self._control = control
        self._ingester = ingester
        self._storage = cape_storage_path
        self._imports_dir = imports_dir

    async def run(self, analysis_id: int, started_at: datetime) -> ImportedImage:
        """Scans the upload and indexes what it holds, leaving the upload where it is.

        Raises `MemoryImportFailedError`, and `IngestFailedError` when the events cannot be stored.
        """
        stored = import_file(self._imports_dir, analysis_id)
        if not stored.is_file():
            raise MemoryImportFailedError(
                "The uploaded file is missing, so the memory image cannot be analysed"
            )
        task_id = image_task_id(analysis_id)
        answered = await self._scan(task_id, f"{analysis_id}/{UPLOAD_NAME}")
        memory = summarise_analysis(answered, stored.stat().st_size)
        if memory.findings is MemoryFindings.FAILED:
            raise MemoryImportFailedError(_why_every_plugin_failed(answered))
        indexed = await self._ingester.ingest_memory_image(
            analysis_id, self._storage / "analyses" / str(task_id), started_at=started_at
        )
        return ImportedImage(indexed, memory)

    async def _scan(self, task_id: int, image: str) -> MemoryAnalysis:
        answered = await self._analyse(task_id, image)
        if answered.missing_symbols is None:
            return answered
        await self._make_symbols(answered.missing_symbols)
        again = await self._analyse(task_id, image)
        if again.missing_symbols is not None:
            raise MemoryImportFailedError(
                f"{_why_every_plugin_failed(again)}, although its symbol file was just made "
                f"(kernel {_kernel_id(again.missing_symbols)})"
            )
        return again

    async def _analyse(self, task_id: int, image: str) -> MemoryAnalysis:
        try:
            return await self._control.analyse_memory(task_id, image)
        except GuestControlError as error:
            raise MemoryImportFailedError(
                f"The memory image could not be analysed: {error}"
            ) from error

    async def _make_symbols(self, missing: MissingSymbols) -> None:
        try:
            await self._control.make_symbols(missing)
        except GuestControlRejected as refused:
            raise MemoryImportFailedError(
                f"The symbols of this Windows build ({_kernel_id(missing)}) are not available "
                f"and could not be fetched: {refused.message}"
            ) from refused
        except GuestControlError as error:
            raise MemoryImportFailedError(
                f"The symbols of this Windows build ({_kernel_id(missing)}) could not be "
                f"fetched: {error}"
            ) from error


def _kernel_id(missing: MissingSymbols) -> str:
    return f"{missing.guid}-{missing.age}"


def _why_every_plugin_failed(answered: MemoryAnalysis) -> str:
    # Every plugin reports the same cause, so it is said once.
    return "; ".join(sorted(set(answered.errors.values())))
