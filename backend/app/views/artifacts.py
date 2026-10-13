import asyncio
import hashlib
import logging
import os
import re
import tempfile
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

from app.analyses.ports import ReportUnreadableError
from app.analyses.summary import load_report
from app.ingest.reading import mapping_list, section, text_or_none, to_int
from app.samples.store import safe_file_name, write_encrypted_zip
from app.schemas.views_events import ProcessRef
from app.schemas.views_findings import Artifact, ArtifactsView, ExtractedConfig, Screenshot

logger = logging.getLogger(__name__)

REPORT_PATH = Path("reports") / "report.json"
PCAP_FILE = "dump.pcap"
MEMORY_DUMP_FILE = "memory.dmp"
SCREENSHOT_DIRECTORY = "shots"
SCREENSHOT_MEDIA_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}
SMALL_SCREENSHOT_SUFFIX = "_small"
ID_LENGTH = 20
_SHA256 = re.compile(r"[0-9a-f]{64}")
_PLAIN_FILE_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
_UNSAFE_NAME_CHARACTER = re.compile(r"[^\w.\- ]")


class ArtifactKind(StrEnum):
    DROPPED = "dropped"
    PAYLOAD = "payload"
    PROCDUMP = "procdump"
    PROCMEMORY = "procmemory"
    CONFIG = "config"
    MEMORY_DUMP = "memory_dump"
    PCAP = "pcap"


@dataclass(frozen=True)
class _Source:
    """Where CAPE keeps the files of one kind. Dropped files, payloads and dumps are stored under
    their SHA256; process memory dumps keep the name CAPE gave them.
    """

    kind: ArtifactKind
    folder: str
    named_by_hash: bool = True


DROPPED = _Source(ArtifactKind.DROPPED, "files")
PAYLOADS = _Source(ArtifactKind.PAYLOAD, "CAPE")
PROCDUMPS = _Source(ArtifactKind.PROCDUMP, "procdump")
PROCMEMORY = _Source(ArtifactKind.PROCMEMORY, "procmemory", named_by_hash=False)


@dataclass(frozen=True)
class ArtifactFile:
    path: Path
    name: str


@dataclass(frozen=True)
class Catalog:
    """What an analysis's report and folder say it produced.

    `files` maps an artifact id to a file proven to be inside the analysis folder: it is the only
    way a download finds a file, so no request text is ever turned into a path.
    """

    view: ArtifactsView
    files: Mapping[str, ArtifactFile] = field(default_factory=dict)
    screenshots: tuple[Path, ...] = ()
    pcap: Path | None = None


@dataclass(frozen=True)
class AnalysisFiles:
    report: Mapping[str, Any] | None
    catalog: Catalog


def download_name(name: str) -> str:
    return _UNSAFE_NAME_CHARACTER.sub("_", safe_file_name(name))


def read_analysis_files(storage_root: Path, cape_task_id: int | None) -> AnalysisFiles:
    """Blocking: parses the report and stats the files. A missing report gives empty collections."""
    if cape_task_id is None:
        return AnalysisFiles(None, build_catalog(None, None))
    directory = storage_root / "analyses" / str(cape_task_id)
    report = _read_report_or_none(directory / REPORT_PATH)
    return AnalysisFiles(report, build_catalog(report, directory if directory.is_dir() else None))


async def pack_for_download(file: ArtifactFile) -> Path:
    """An encrypted zip of the file in a temporary file the caller must delete."""
    descriptor, temporary = await asyncio.to_thread(
        tempfile.mkstemp, prefix="artifact-", suffix=".zip"
    )
    os.close(descriptor)
    packed = Path(temporary)
    try:
        await asyncio.to_thread(write_encrypted_zip, file.path, download_name(file.name), packed)
    except Exception:
        await asyncio.to_thread(packed.unlink, True)
        raise
    return packed


def build_catalog(report: Mapping[str, Any] | None, directory: Path | None) -> Catalog:
    report = report or {}
    builder = _CatalogBuilder(directory, _process_names(report))
    cape = section(report, "CAPE")
    dropped = builder.artifacts(DROPPED, mapping_list(report.get("dropped")))
    payloads = builder.artifacts(PAYLOADS, mapping_list(cape.get("payloads")))
    procdumps = builder.artifacts(PROCDUMPS, mapping_list(report.get("procdump")))
    procdumps += builder.artifacts(PROCMEMORY, mapping_list(report.get("procmemory")))
    pcap_hash = text_or_none(section(report, "network").get("pcap_sha256"))
    pcap = builder.fixed_file(ArtifactKind.PCAP, PCAP_FILE, pcap_hash)
    view = ArtifactsView(
        dropped=dropped,
        payloads=payloads,
        procdumps=procdumps,
        memory_dump=builder.fixed_file(ArtifactKind.MEMORY_DUMP, MEMORY_DUMP_FILE),
        pcap=pcap,
        screenshots=builder.screenshots,
        configs=builder.configs(mapping_list(cape.get("configs"))),
    )
    pcap_file = builder.files.get(pcap.id) if pcap else None
    return Catalog(
        view,
        builder.files,
        tuple(builder.screenshot_files),
        pcap_file.path if pcap_file else None,
    )


def _read_report_or_none(path: Path) -> dict[str, Any] | None:
    try:
        return load_report(path)
    except ReportUnreadableError as problem:
        logger.info("No artifacts from the report: %s", problem)
        return None


def _process_names(report: Mapping[str, Any]) -> dict[int, str | None]:
    processes = mapping_list(section(report, "behavior").get("processes"))
    return {
        pid: text_or_none(process.get("process_name"))
        for process in processes
        if (pid := to_int(process.get("process_id"))) is not None
    }


def _artifact_id(kind: ArtifactKind, key: str, occurrence: int) -> str:
    digest = hashlib.sha256(f"{kind}:{key}:{occurrence}".encode()).hexdigest()
    return digest[:ID_LENGTH]


def _first_text(value: object) -> str | None:
    if isinstance(value, list):
        return next((text for item in value if (text := text_or_none(item))), None)
    return text_or_none(value)


def _yara_names(entry: Mapping[str, Any]) -> list[str]:
    names: dict[str, None] = {}
    for key in ("yara", "cape_yara"):
        hits = entry.get(key)
        for hit in hits if isinstance(hits, list) else []:
            name = text_or_none(hit.get("name") if isinstance(hit, Mapping) else hit)
            if name:
                names[name] = None
    return list(names)


class _CatalogBuilder:
    def __init__(self, directory: Path | None, process_names: Mapping[int, str | None]) -> None:
        self._directory = directory.resolve() if directory else None
        self._process_names = process_names
        self._seen: Counter[tuple[ArtifactKind, str]] = Counter()
        self.files: dict[str, ArtifactFile] = {}
        self.screenshots: list[Screenshot] = []
        self.screenshot_files: list[Path] = []
        if self._directory:
            self._find_screenshots(self._directory)

    def artifacts(self, source: _Source, entries: list[Mapping[str, Any]]) -> list[Artifact]:
        return [self._artifact(source, entry) for entry in entries]

    def fixed_file(
        self, kind: ArtifactKind, file_name: str, sha256: str | None = None
    ) -> Artifact | None:
        found = self._inside(file_name)
        if found is None:
            return None
        artifact = Artifact(
            id=self._next_id(kind, file_name),
            name=file_name,
            size=found.stat().st_size,
            sha256=sha256,
            md5=None,
            type=None,
            cape_type=None,
            yara=[],
            source_process=None,
            guest_path=None,
            downloadable=True,
        )
        self.files[artifact.id] = ArtifactFile(found, file_name)
        return artifact

    def configs(self, entries: list[Mapping[str, Any]]) -> list[ExtractedConfig]:
        return [
            ExtractedConfig(
                id=self._next_id(ArtifactKind.CONFIG, str(family)),
                family=str(family),
                data=dict(data),
            )
            for entry in entries
            for family, data in entry.items()
            if isinstance(data, Mapping)
        ]

    def _artifact(self, source: _Source, entry: Mapping[str, Any]) -> Artifact:
        sha256 = text_or_none(entry.get("sha256"))
        disk_name = self._disk_name(source, entry, sha256)
        found = self._inside(source.folder, disk_name) if disk_name else None
        name = self._display_name(source, entry) or sha256 or "unnamed"
        artifact = Artifact(
            id=self._next_id(source.kind, sha256 or disk_name or name),
            name=name,
            size=to_int(entry.get("size")) if found is None else found.stat().st_size,
            sha256=sha256,
            md5=text_or_none(entry.get("md5")),
            type=text_or_none(entry.get("type")),
            cape_type=text_or_none(entry.get("cape_type")),
            yara=_yara_names(entry),
            source_process=self._source_process(entry),
            guest_path=_guest_path(entry),
            downloadable=found is not None,
        )
        if found is not None:
            self.files[artifact.id] = ArtifactFile(found, name)
        return artifact

    @staticmethod
    def _disk_name(source: _Source, entry: Mapping[str, Any], sha256: str | None) -> str | None:
        if source.named_by_hash:
            return sha256 if sha256 and _SHA256.fullmatch(sha256) else None
        recorded = text_or_none(entry.get("file")) or text_or_none(entry.get("path"))
        plain = Path(recorded.replace("\\", "/")).name if recorded else ""
        return plain if _PLAIN_FILE_NAME.fullmatch(plain) else None

    @staticmethod
    def _display_name(source: _Source, entry: Mapping[str, Any]) -> str | None:
        if source.kind in (ArtifactKind.PROCDUMP, ArtifactKind.PROCMEMORY):
            return text_or_none(entry.get("process_name")) or _first_text(entry.get("name"))
        return _first_text(entry.get("name"))

    def _source_process(self, entry: Mapping[str, Any]) -> ProcessRef | None:
        pid = to_int(entry.get("pid"))
        if pid is None:
            return None
        return ProcessRef(
            pid=pid, name=self._process_names.get(pid) or text_or_none(entry.get("process_name"))
        )

    def _next_id(self, kind: ArtifactKind, key: str) -> str:
        occurrence = self._seen[(kind, key)]
        self._seen[(kind, key)] += 1
        return _artifact_id(kind, key, occurrence)

    def _inside(self, *relative: str) -> Path | None:
        """The regular file at `relative` under the analysis folder, after following links."""
        if self._directory is None:
            return None
        try:
            resolved = self._directory.joinpath(*relative).resolve(strict=True)
        except OSError:
            return None
        inside = resolved.is_relative_to(self._directory)
        return resolved if inside and resolved.is_file() else None

    def _find_screenshots(self, directory: Path) -> None:
        folder = directory / SCREENSHOT_DIRECTORY
        try:
            names = sorted(path.name for path in folder.iterdir())
        except OSError:
            return
        for name in names:
            shot = Path(name)
            is_full_size = not shot.stem.endswith(SMALL_SCREENSHOT_SUFFIX)
            found = self._inside(SCREENSHOT_DIRECTORY, name)
            if found and is_full_size and shot.suffix.lower() in SCREENSHOT_MEDIA_TYPES:
                self.screenshot_files.append(found)
                self.screenshots.append(
                    Screenshot(n=len(self.screenshots) + 1, name=name, size=found.stat().st_size)
                )


def _guest_path(entry: Mapping[str, Any]) -> str | None:
    return (
        text_or_none(entry.get("process_path"))
        or _first_text(entry.get("guest_paths"))
        or text_or_none(entry.get("module_path"))
    )
