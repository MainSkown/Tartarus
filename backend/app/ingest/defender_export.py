"""Reads a guest's Defender export and says what each record means.

Scope, action, outcome, severity and run time are decided here and nowhere else: the normaliser and
the analysis verdict both go through `read_export`, so they cannot disagree about a detection.
"""

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from pathlib import Path
from typing import Any

from app.ingest.clock import analysis_clock_offset
from app.ingest.protocol import IngestContext
from app.ingest.reading import mapping_list, sample_file_name, section, text_or_none, to_int
from app.ingest.windows_events import WindowsEvent, read_windows_events

EXPORT_PARTS = ("aux", "defender.xml")
DETECTED = 1116
ACTION_TAKEN = 1117
ACTION_FAILED = frozenset({1118, 1119})
HANDLED_EVENTS = frozenset({DETECTED, ACTION_TAKEN, *ACTION_FAILED})
REMOVING_ACTIONS = {2: "quarantine", 3: "remove"}
SEVERITY_LEVELS = {5: 4, 4: 3, 2: 2, 1: 1}
DEFAULT_SEVERITY = 2
FILE_PREFIX = "file:_"
TOOLING_PATH = re.compile(r"^[A-Za-z]:\\[^\\]{8}\\(bin|dll|lib|data)\\", re.IGNORECASE)


class Scope(StrEnum):
    TOOLING = "tooling"
    SAMPLE = "sample"
    DROPPED = "dropped"
    OTHER = "other"


class Outcome(StrEnum):
    REMOVED = "removed"
    FAILED = "failed"
    PENDING = "pending"


@dataclass(frozen=True)
class SampleFacts:
    """What the analysis knows about its sample: the upload folder, its name and its processes."""

    task_id: str | None
    sample_name: str | None
    images: frozenset[str]


@dataclass(frozen=True)
class Detection:
    detection_id: str
    scope: Scope
    records: tuple[WindowsEvent, ...]

    @property
    def lead(self) -> WindowsEvent:
        return _lead(self.records)

    @property
    def detected(self) -> WindowsEvent | None:
        return next((record for record in self.records if record.event_id == DETECTED), None)

    @property
    def removal(self) -> WindowsEvent | None:
        return next(
            (
                record
                for record in self.records
                if record.event_id == ACTION_TAKEN and removing_action(record) is not None
            ),
            None,
        )

    @property
    def action(self) -> str:
        removal = self.removal
        return "none" if removal is None else removing_action(removal) or "none"

    @property
    def outcome(self) -> Outcome:
        if any(record.event_id in ACTION_FAILED for record in self.records):
            return Outcome.FAILED
        return Outcome.PENDING if self.removal is None else Outcome.REMOVED


@dataclass(frozen=True)
class Export:
    """The parsed export of one analysis, with the clock it is read on."""

    records: tuple[WindowsEvent, ...]
    detections: Mapping[str, Detection]
    offset: timedelta
    started_at: datetime

    def detection_of(self, record: WindowsEvent) -> Detection | None:
        detection_id = text_of(record, "Detection ID")
        return None if detection_id is None else self.detections.get(detection_id)

    def run_time(self, record: WindowsEvent) -> tuple[datetime, bool] | None:
        """UTC time of a record, and whether it sits before the run on the snapshot's clock.

        Records written before the analysis started (the sample's own detection, stamped when the
        snapshot was taken) are placed at the analysis start.
        """
        if record.system_time is None:
            return None
        moment = record.system_time + self.offset
        if moment < self.started_at:
            return self.started_at, True
        return moment, False


def read_export(report: Mapping[str, Any], context: IngestContext) -> Export | None:
    """None when the analysis has no export file (or no folder to look in)."""
    path = _export_path(context)
    if path is None:
        return None
    records = tuple(read_windows_events(path))
    return Export(
        records=records,
        detections=classify(records, sample_facts(report)),
        offset=analysis_clock_offset(report, context),
        started_at=context.started_at,
    )


def _export_path(context: IngestContext) -> Path | None:
    if context.analysis_dir is None:
        return None
    path = context.analysis_dir.joinpath(*EXPORT_PARTS)
    return path if path.is_file() else None


def sample_facts(report: Mapping[str, Any]) -> SampleFacts:
    task_id = to_int(section(report, "info").get("id"))
    images = frozenset(
        image.lower()
        for entry in mapping_list(section(report, "behavior").get("processes"))
        if (image := text_or_none(entry.get("module_path")))
    )
    return SampleFacts(
        task_id=None if task_id is None else str(task_id),
        sample_name=sample_file_name(report),
        images=images,
    )


def classify(records: Sequence[WindowsEvent], facts: SampleFacts) -> dict[str, Detection]:
    """Groups the handled records by Detection ID and scopes each group by its first record."""
    grouped: dict[str, list[WindowsEvent]] = {}
    for record in records:
        detection_id = text_of(record, "Detection ID")
        if record.event_id in HANDLED_EVENTS and detection_id is not None:
            grouped.setdefault(detection_id, []).append(record)
    return {
        detection_id: Detection(detection_id, scope_of(_lead(group), facts), tuple(group))
        for detection_id, group in grouped.items()
    }


def scope_of(record: WindowsEvent, facts: SampleFacts) -> Scope:
    path = file_path_of(record)
    if path is not None and TOOLING_PATH.match(path):
        return Scope.TOOLING
    if path is not None and _in_sample_folder(path, facts):
        return Scope.SAMPLE
    process = text_of(record, "Process Name")
    if process is not None and process.lower() in facts.images:
        return Scope.DROPPED
    return Scope.OTHER


def _in_sample_folder(path: str, facts: SampleFacts) -> bool:
    lowered = path.lower()
    if facts.task_id is not None and f"\\temp\\{facts.task_id}\\" in lowered:
        return True
    return facts.sample_name is not None and lowered.endswith(
        f"\\temp\\{facts.sample_name.lower()}"
    )


def removing_action(record: WindowsEvent) -> str | None:
    action_id = to_int(record.data.get("Action ID"))
    return None if action_id is None else REMOVING_ACTIONS.get(action_id)


def severity_of(record: WindowsEvent) -> int:
    severity_id = to_int(record.data.get("Severity ID"))
    if severity_id is None:
        return DEFAULT_SEVERITY
    return SEVERITY_LEVELS.get(severity_id, DEFAULT_SEVERITY)


def file_path_of(record: WindowsEvent) -> str | None:
    raw = text_of(record, "Path")
    if raw is None or not raw.startswith(FILE_PREFIX):
        return None
    return raw[len(FILE_PREFIX) :]


def text_of(record: WindowsEvent, name: str) -> str | None:
    value = record.data.get(name, "").strip()
    return value or None


def int_of(record: WindowsEvent, name: str) -> int | None:
    return to_int(record.data.get(name))


def _lead(records: Sequence[WindowsEvent]) -> WindowsEvent:
    return next((record for record in records if record.event_id == DETECTED), records[0])
