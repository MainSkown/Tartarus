import hashlib
import itertools
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from app.analyses.summary import SEVERITY_ORDER, severity_from_cape
from app.ingest.protocol import IngestContext

LANES = ("process", "file", "registry", "network", "memory", "api")
RESERVED_SECTIONS = ("@timestamp", "event", "tartarus")
REGISTRY_HIVES = {
    "HKEY_LOCAL_MACHINE": "HKLM",
    "HKEY_CURRENT_USER": "HKCU",
    "HKEY_CLASSES_ROOT": "HKCR",
    "HKEY_USERS": "HKU",
    "HKEY_CURRENT_CONFIG": "HKCC",
}


def event_id(analysis_id: int, source: str, source_file: str, record_index: int) -> str:
    identity = f"{analysis_id}|{source}|{source_file}|{record_index}"
    return hashlib.sha1(identity.encode(), usedforsecurity=False).hexdigest()


def format_timestamp(moment: datetime) -> str:
    if moment.tzinfo is None:
        raise ValueError("timestamp must carry a timezone")
    return moment.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def process_entity_id(analysis_id: int, pid: int, start: datetime | None) -> str:
    if start is None:
        return f"{analysis_id}:{pid}"
    return f"{analysis_id}:{pid}@{format_timestamp(start)}"


def severity_level(cape_severity: object) -> int:
    """CAPE's 1-3 signature scale (4+ is critical) as the 0-4 `event.severity`."""
    return SEVERITY_ORDER.index(severity_from_cape(cape_severity))


def related_events(*event_ids: str) -> dict[str, Any]:
    return {"events": list(event_ids)}


def base_name(path: str) -> str:
    return path.replace("/", "\\").rsplit("\\", 1)[-1]


def file_fields(path: str, target_path: str | None = None) -> dict[str, Any]:
    name = base_name(path)
    fields: dict[str, Any] = {"path": path, "name": name}
    extension = name.rpartition(".")[2] if "." in name else ""
    if extension:
        fields["extension"] = extension.lower()
    if target_path is not None:
        fields["target_path"] = target_path
    return fields


def registry_fields(
    path: str,
    *,
    value_name: str | None = None,
    data_type: str | None = None,
    data: str | None = None,
) -> dict[str, Any]:
    hive, _, key = path.partition("\\")
    fields: dict[str, Any] = {"path": path, "hive": REGISTRY_HIVES.get(hive.upper(), hive)}
    if value_name:
        key = _strip_value_name(key, value_name)
        fields["value"] = value_name
    if key:
        fields["key"] = key
    if data_type is not None or data is not None:
        fields["data"] = _registry_data(data_type, data)
    return fields


def _strip_value_name(key: str, value_name: str) -> str:
    suffix = f"\\{value_name}".lower()
    return key[: -len(suffix)] if key.lower().endswith(suffix) else key


def _registry_data(data_type: str | None, data: str | None) -> dict[str, Any]:
    fields: dict[str, Any] = {}
    if data_type is not None:
        fields["type"] = data_type
    if data is not None:
        fields["strings"] = [data]
    return fields


@dataclass(frozen=True)
class ProcessIdentity:
    pid: int
    parent_pid: int | None = None
    name: str | None = None
    executable: str | None = None
    command_line: str | None = None
    start: datetime | None = None
    parent_name: str | None = None


def process_fields(
    process: ProcessIdentity, analysis_id: int, thread_id: int | None = None
) -> dict[str, Any]:
    fields: dict[str, Any] = {
        "pid": process.pid,
        "entity_id": process_entity_id(analysis_id, process.pid, process.start),
    }
    optional = {
        "name": process.name,
        "executable": process.executable,
        "command_line": process.command_line,
        "start": None if process.start is None else format_timestamp(process.start),
    }
    fields |= {key: value for key, value in optional.items() if value is not None}
    parent = {"pid": process.parent_pid, "name": process.parent_name}
    parent = {key: value for key, value in parent.items() if value is not None}
    if parent:
        fields["parent"] = parent
    if thread_id is not None:
        fields["thread"] = {"id": thread_id}
    return fields


@dataclass(frozen=True)
class EventShape:
    """What kind of event this is; the same shape is reused for every event of that kind."""

    action: str
    categories: tuple[str, ...]
    types: tuple[str, ...]
    lane: str
    dataset: str
    kind: str = "event"

    def __post_init__(self) -> None:
        if self.lane not in LANES:
            raise ValueError(f"unknown lane {self.lane!r}")


@dataclass(frozen=True)
class SourceRecord:
    """One record of the source: its position, when it happened, and the original.

    `source_file` overrides the factory's when one record yields events with distinct identities.
    """

    index: int
    timestamp: datetime
    raw: Mapping[str, Any]
    source_file: str | None = None


class EventFactory:
    """Builds event documents for one source of one analysis and numbers them in build order."""

    def __init__(
        self, context: IngestContext, *, source: str, source_file: str, module: str
    ) -> None:
        self._context = context
        self._source = source
        self._source_file = source_file
        self._module = module
        self._sequence = itertools.count()

    def build(
        self,
        shape: EventShape,
        record: SourceRecord,
        summary: str,
        *,
        severity: int = 0,
        **sections: Any,
    ) -> dict[str, Any]:
        for name in RESERVED_SECTIONS:
            if name in sections:
                raise ValueError(f"section {name!r} would overwrite a common field")
        return {
            "@timestamp": format_timestamp(record.timestamp),
            "event": {
                "id": event_id(
                    self._context.analysis_id,
                    self._source,
                    record.source_file or self._source_file,
                    record.index,
                ),
                "sequence": next(self._sequence),
                "kind": shape.kind,
                "category": list(shape.categories),
                "type": list(shape.types),
                "action": shape.action,
                "module": self._module,
                "dataset": shape.dataset,
                "severity": severity,
            },
            "tartarus": {
                "analysis_id": self._context.analysis_id,
                "lane": shape.lane,
                "phase": "final",
                "summary": summary,
                "raw": record.raw,
            },
            **sections,
        }
