"""What Defender did to an analysis's sample, from its export: the `defender` summary object.

Built on the same classification as the normaliser (`app.ingest.defender_export`), so the summary
and the events always agree. Definition: docs/plans/m8-spikes/S4-findings.md, "Verdict definition".
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from app.ingest.defender_export import (
    Detection,
    Export,
    Outcome,
    Scope,
    file_path_of,
    int_of,
    read_export,
    severity_of,
    text_of,
)
from app.ingest.ecs import format_timestamp
from app.ingest.protocol import IngestContext
from app.ingest.windows_events import WindowsEvent

CONSEQUENTIAL_SCOPES = frozenset({Scope.SAMPLE, Scope.DROPPED})


@dataclass(frozen=True)
class Threat:
    detection_id: str
    threat_id: int | None
    name: str | None
    severity: int
    category_id: int | None
    scope: Scope
    path: str | None
    process: str | None
    user: str | None
    detected_at: str | None
    action: str
    outcome: Outcome
    removed_at: str | None

    def as_json(self) -> dict[str, Any]:
        return {
            "detection_id": self.detection_id,
            "threat_id": self.threat_id,
            "name": self.name,
            "severity": self.severity,
            "category_id": self.category_id,
            "scope": self.scope.value,
            "path": self.path,
            "process": self.process,
            "user": self.user,
            "detected_at": self.detected_at,
            "action": self.action,
            "outcome": self.outcome.value,
            "removed_at": self.removed_at,
        }


def defender_verdict(
    report: Mapping[str, Any], context: IngestContext, process_count: int
) -> dict[str, Any]:
    """`process_count` is how many processes the run monitored: none means the sample never ran."""
    export = read_export(report, context)
    if export is None:
        return _summary("no_export", [], process_count)
    threats = [
        _threat(detection, export)
        for detection in export.detections.values()
        if detection.scope in CONSEQUENTIAL_SCOPES
    ]
    return _summary(_status(threats), threats, process_count)


def _summary(status: str, threats: list[Threat], process_count: int) -> dict[str, Any]:
    sample_removed = any(
        threat.scope is Scope.SAMPLE and threat.outcome is Outcome.REMOVED for threat in threats
    )
    return {
        "status": status,
        "sample_removed": sample_removed,
        "blocked_before_run": sample_removed and process_count == 0,
        "threats": [threat.as_json() for threat in threats],
    }


def _status(threats: list[Threat]) -> str:
    if not threats:
        return "clean"
    outcomes = {threat.outcome for threat in threats}
    if Outcome.FAILED in outcomes:
        return "failed"
    if Outcome.REMOVED in outcomes:
        return "removed"
    return "detected"


def _threat(detection: Detection, export: Export) -> Threat:
    lead = detection.lead
    path = file_path_of(lead)
    return Threat(
        detection_id=detection.detection_id,
        threat_id=int_of(lead, "Threat ID"),
        name=text_of(lead, "Threat Name"),
        severity=severity_of(lead),
        category_id=int_of(lead, "Category ID"),
        scope=detection.scope,
        path=path,
        process=text_of(lead, "Process Name"),
        user=text_of(lead, "Detection User"),
        detected_at=_moment(export, detection.detected),
        action=detection.action,
        outcome=detection.outcome,
        removed_at=_moment(export, detection.removal),
    )


def _moment(export: Export, record: WindowsEvent | None) -> str | None:
    if record is None:
        return None
    run_time = export.run_time(record)
    return None if run_time is None else format_timestamp(run_time[0])
