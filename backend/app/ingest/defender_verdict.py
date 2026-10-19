"""What Defender did to an analysis's sample, from its export: the `defender` summary object.

Built on the same classification as the normaliser (`app.ingest.defender_export`), so the summary
and the events always agree. Definition: docs/plans/m8-spikes/S4-findings.md, "Verdict definition".
"""

from collections.abc import Iterable, Mapping
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
    threats = collapse_repeated_threats(
        [
            _threat(detection, export)
            for detection in export.detections.values()
            if detection.scope in CONSEQUENTIAL_SCOPES
        ]
    )
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
    outcome = _settled_outcome({threat.outcome for threat in threats})
    if outcome is Outcome.FAILED:
        return DefenderStatus.FAILED
    if outcome is Outcome.REMOVED:
        return DefenderStatus.REMOVED
    return DefenderStatus.DETECTED


_RepeatKey = tuple[int | None, str | None, str | None, Scope]


# Defender can report one file again under a new Detection ID (R2 saw the EICAR file twice, 15 s
# apart). The group is one threat, and one failed action means a copy may still be on disk, so
# failure outranks removal and removal outranks a pending detection.
def collapse_repeated_threats(threats: list[DefenderThreat]) -> list[DefenderThreat]:
    groups: dict[_RepeatKey, list[DefenderThreat]] = {}
    for threat in threats:
        groups.setdefault(_repeat_key(threat), []).append(threat)
    return [_one_threat(group) for group in groups.values()]


def _repeat_key(threat: DefenderThreat) -> _RepeatKey:
    name_when_unidentified = None if threat.threat_id is not None else threat.name
    path = None if threat.path is None else threat.path.lower()
    return (threat.threat_id, name_when_unidentified, path, threat.scope)


def _one_threat(group: list[DefenderThreat]) -> DefenderThreat:
    outcome = _settled_outcome({threat.outcome for threat in group})
    representative = next(threat for threat in group if threat.outcome is outcome)
    return representative.model_copy(
        update={
            "outcome": outcome,
            "detected_at": _earliest(threat.detected_at for threat in group),
            "removed_at": _latest(threat.removed_at for threat in group),
        }
    )


def _settled_outcome(outcomes: set[Outcome]) -> Outcome:
    if Outcome.FAILED in outcomes:
        return Outcome.FAILED
    if Outcome.REMOVED in outcomes:
        return Outcome.REMOVED
    return Outcome.PENDING


def _earliest(moments: Iterable[str | None]) -> str | None:
    return min((moment for moment in moments if moment is not None), default=None)


def _latest(moments: Iterable[str | None]) -> str | None:
    return max((moment for moment in moments if moment is not None), default=None)


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
