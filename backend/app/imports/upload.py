"""Queues an imported analysis from an uploaded capture or memory image."""

import asyncio
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, BinaryIO

from sqlalchemy.ext.asyncio import AsyncSession

from app.analyses.ports import RunnerControl
from app.analyses.submission import queue_analysis
from app.config import Settings
from app.db.analysis_repository import delete_analysis, delete_sample_if_unreferenced
from app.db.models import Analysis
from app.db.models.analysis import AnalysisKind
from app.imports.sniff import ImportKind, sniff_import
from app.samples.store import CHUNK_SIZE, ByteSource, Digests, EmptySampleError, safe_file_name

UPLOAD_NAME = "upload"
MEMORY_IMAGE_PATH = "/api/analyses/import/memory-image"
# CAPE's container reads the upload through a read-only mount and is not the backend's user.
READABLE_BY_OTHERS = 0o644
TRAVERSABLE_BY_OTHERS = 0o755
_INCOMING = ".incoming"


class UnsupportedImportError(Exception):
    """The file is neither a capture nor (where accepted) a memory image."""


class ImportTooLargeError(Exception):
    def __init__(self, max_bytes: int) -> None:
        super().__init__(f"import is larger than {max_bytes} bytes")
        self.max_bytes = max_bytes


@dataclass(frozen=True)
class ImportLimits:
    pcap_bytes: int
    memory_image_bytes: int

    def of(self, kind: ImportKind) -> int:
        return self.memory_image_bytes if kind is ImportKind.MEMORY_IMAGE else self.pcap_bytes


def import_directory(imports_dir: Path, analysis_id: int) -> Path:
    return imports_dir / str(analysis_id)


def import_file(imports_dir: Path, analysis_id: int) -> Path:
    return import_directory(imports_dir, analysis_id) / UPLOAD_NAME


class ImportSubmitter:
    """Streams an upload to `<imports_dir>/<analysis id>/upload` and queues the analysis."""

    def __init__(self, imports_dir: Path, limits: ImportLimits, runner: RunnerControl) -> None:
        self._imports_dir = imports_dir
        self._limits = limits
        self._runner = runner

    @classmethod
    def from_settings(cls, settings: Settings, runner: RunnerControl) -> "ImportSubmitter":
        limits = ImportLimits(
            settings.import_pcap_max_bytes, settings.import_memory_image_max_bytes
        )
        return cls(settings.imports_dir, limits, runner)

    async def submit(
        self,
        session: AsyncSession,
        stream: ByteSource,
        filename: str,
        *,
        accept_memory_image: bool,
    ) -> Analysis:
        """Raises `UnsupportedImportError`, `ImportTooLargeError` and the sample store's
        `EmptySampleError`. Nothing is kept when any of them is raised.

        The sample is recorded by its hashes only and keeps no copy in the sample store: its
        `stored_path` is the imports directory, since the bytes live under the analysis.
        """
        name = safe_file_name(filename)
        incoming = await asyncio.to_thread(self._make_incoming_directory)
        try:
            upload = incoming / UPLOAD_NAME
            kind, digests = await self._receive(stream, upload, accept_memory_image)
            stored = digests.kept_at(self._imports_dir)
            options = {
                "import": {"kind": _recorded_kind(kind), "filename": name, "size": stored.size}
            }
            analysis = await queue_analysis(session, stored, name, options, AnalysisKind.IMPORTED)
            await self._move_into_place(session, upload, analysis, stored.sha256)
        finally:
            await asyncio.to_thread(shutil.rmtree, incoming, True)
        self._runner.nudge()
        return analysis

    async def _move_into_place(
        self, session: AsyncSession, upload: Path, analysis: Analysis, sha256: str
    ) -> None:
        try:
            await asyncio.to_thread(self._place, upload, analysis.id)
        except Exception:
            await delete_analysis(session, analysis.id)
            await delete_sample_if_unreferenced(session, sha256)
            await asyncio.to_thread(
                shutil.rmtree, import_directory(self._imports_dir, analysis.id), True
            )
            raise

    def _make_incoming_directory(self) -> Path:
        self._imports_dir.mkdir(mode=TRAVERSABLE_BY_OTHERS, parents=True, exist_ok=True)
        return Path(tempfile.mkdtemp(prefix=f"{_INCOMING}-", dir=self._imports_dir))

    def _place(self, upload: Path, analysis_id: int) -> None:
        directory = import_directory(self._imports_dir, analysis_id)
        directory.mkdir(mode=TRAVERSABLE_BY_OTHERS)
        upload.chmod(READABLE_BY_OTHERS)
        upload.replace(directory / UPLOAD_NAME)

    async def _receive(
        self, stream: ByteSource, destination: Path, accept_memory_image: bool
    ) -> tuple[ImportKind, Digests]:
        head = await stream.read(CHUNK_SIZE)
        if not head:
            raise EmptySampleError
        kind = _accepted_kind(head, accept_memory_image)
        limit = self._limits.of(kind)
        digests = Digests()
        with destination.open("xb") as out:
            chunk = head
            while chunk:
                if digests.size + len(chunk) > limit:
                    raise ImportTooLargeError(limit)
                await asyncio.to_thread(_absorb, chunk, digests, out)
                chunk = await stream.read(CHUNK_SIZE)
        return kind, digests


def _accepted_kind(head: bytes, accept_memory_image: bool) -> ImportKind:
    kind = sniff_import(head)
    if kind is ImportKind.UNSUPPORTED:
        raise UnsupportedImportError(
            "The file is neither a PCAP or PCAPNG capture nor a memory image"
        )
    if kind is ImportKind.MEMORY_IMAGE and not accept_memory_image:
        raise UnsupportedImportError(
            f"A memory image goes to {MEMORY_IMAGE_PATH}, not to this path"
        )
    return kind


def recorded_import_kind(options: dict[str, Any]) -> object:
    """The kind an import's options record (`pcap` or `memory_image`); None for a run's."""
    recorded = options.get("import")
    return recorded.get("kind") if isinstance(recorded, dict) else None


def _recorded_kind(kind: ImportKind) -> str:
    return (
        ImportKind.MEMORY_IMAGE.value if kind is ImportKind.MEMORY_IMAGE else ImportKind.PCAP.value
    )


def _absorb(chunk: bytes, digests: Digests, out: BinaryIO) -> None:
    digests.update(chunk)
    out.write(chunk)
