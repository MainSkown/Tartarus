"""What Defender did to an analysis's sample, from its export: the `defender` summary object.

Built on the same classification as the normaliser (`app.ingest.defender_export`), so the summary
and the events always agree. Definition: docs/plans/m8-spikes/S4-findings.md, "Verdict definition".
"""

from collections.abc import Mapping
from typing import Any

from app.analyses.defender import DefenderStatus, DefenderThreat, DefenderVerdict
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


def defender_verdict(
    report: Mapping[str, Any], context: IngestContext, process_count: int
) -> DefenderVerdict:
    """`process_count` is how many processes the run monitored: none means the sample never ran."""
    return verdict_of_export(read_export(report, context), process_count)


def verdict_of_export(export: Export | None, process_count: int) -> DefenderVerdict:
    """The verdict of an export already read, so the normaliser and the verdict share one read."""
    if export is None:
        return _verdict(DefenderStatus.NO_EXPORT, [], process_count)
    threats = [
        _threat(detection, export)
        for detection in export.detections.values()
        if detection.scope in CONSEQUENTIAL_SCOPES
    ]
    return _verdict(_status(threats), threats, process_count)


def _verdict(
    status: DefenderStatus, threats: list[DefenderThreat], process_count: int
) -> DefenderVerdict:
    sample_removed = any(
        threat.scope is Scope.SAMPLE and threat.outcome is Outcome.REMOVED for threat in threats
    )
    return DefenderVerdict(
        status=status,
        sample_removed=sample_removed,
        blocked_before_run=sample_removed and process_count == 0,
        threats=threats,
    )


def _status(threats: list[DefenderThreat]) -> DefenderStatus:
    if not threats:
        return DefenderStatus.CLEAN
    outcomes = {threat.outcome for threat in threats}
    if Outcome.FAILED in outcomes:
        return DefenderStatus.FAILED
    if Outcome.REMOVED in outcomes:
        return DefenderStatus.REMOVED
    return DefenderStatus.DETECTED


def _threat(detection: Detection, export: Export) -> DefenderThreat:
    lead = detection.lead
    path = file_path_of(lead)
    return DefenderThreat(
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
