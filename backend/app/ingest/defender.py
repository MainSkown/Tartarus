"""Turns the host-collected Defender export (`aux/defender.xml`) into alert and action events.

What each record means is decided in `app.ingest.defender_export`; this module maps it onto the
field catalog. CAPE's own tooling detections are not events: they are counted instead.
"""

from collections.abc import Iterator, Mapping
from typing import Any

from app.ingest import ecs
from app.ingest.defender_export import (
    ACTION_FAILED,
    DETECTED,
    HANDLED_EVENTS,
    Detection,
    Export,
    Scope,
    file_path_of,
    int_of,
    read_export,
    removing_action,
    severity_of,
    text_of,
)
from app.ingest.ecs import EventFactory, EventShape, SourceRecord, detection_match, related_events
from app.ingest.protocol import IngestContext
from app.ingest.windows_events import WindowsEvent

SOURCE = "defender"
SOURCE_FILE = "defender"
MODULE = "defender"
DATASET = "defender.operational"
RULESET = "defender"
LANE = "file"
CATEGORIES = ("malware", "file")
ACTION_EVENTS = {"quarantine": "malware-quarantined", "remove": "malware-removed"}
ACTION_VERBS = {"quarantine": "quarantined", "remove": "removed", "none": "acted on"}
FAILURE_SEVERITY = 3


class DefenderNormalizer:
    """Defender's detections become alerts; their actions become events linked to them.

    Time and clock rules: docs/plans/m8-spikes/S4-findings.md, "Normaliser mapping".

    `export` is what the last `normalise` call read, kept so the analysis verdict comes from the
    same read; like `ignored_tooling_detections` it belongs to one ingest at a time.
    """

    source = SOURCE

    def __init__(self) -> None:
        self.ignored_tooling_detections = 0
        self.export: Export | None = None

    def normalise(
        self, report: Mapping[str, Any], context: IngestContext
    ) -> Iterator[dict[str, Any]]:
        self.ignored_tooling_detections = 0
        self.export = export = read_export(report, context)
        if export is None:
            return
        factory = EventFactory(context, source=SOURCE, source_file=SOURCE_FILE, module=MODULE)
        for record in export.records:
            detection = export.detection_of(record)
            if detection is None or record.event_id not in HANDLED_EVENTS:
                continue
            if detection.scope is Scope.TOOLING:
                self.ignored_tooling_detections += record.event_id == DETECTED
                continue
            if (event := _event(record, detection, export, factory, context)) is not None:
                yield event


def _event(
    record: WindowsEvent,
    detection: Detection,
    export: Export,
    factory: EventFactory,
    context: IngestContext,
) -> dict[str, Any] | None:
    moment = export.run_time(record)
    if record.record_id is None or moment is None:
        return None
    when, on_snapshot_clock = moment
    return factory.build(
        _shape(record),
        SourceRecord(record.record_id, when, _raw(record)),
        _summary(record),
        severity=_severity(record),
        tartarus=_tartarus(record, detection, on_snapshot_clock),
        rule=_rule(record),
        **_sections(record, detection, context.analysis_id),
    )


def _shape(record: WindowsEvent) -> EventShape:
    if record.event_id == DETECTED:
        return EventShape(
            "malware-detected", CATEGORIES, ("info", "indicator"), LANE, DATASET, "alert"
        )
    if record.event_id in ACTION_FAILED:
        return EventShape(
            "malware-action-failed", CATEGORIES, ("info",), LANE, DATASET, outcome="failure"
        )
    action = removing_action(record)
    if action is None:
        return EventShape(
            "malware-action-taken", CATEGORIES, ("info",), LANE, DATASET, outcome="success"
        )
    return EventShape(
        ACTION_EVENTS[action], CATEGORIES, ("deletion",), LANE, DATASET, outcome="success"
    )


def _severity(record: WindowsEvent) -> int:
    if record.event_id == DETECTED:
        return severity_of(record)
    return FAILURE_SEVERITY if record.event_id in ACTION_FAILED else 0


def _summary(record: WindowsEvent) -> str:
    name = text_of(record, "Threat Name") or "a threat"
    file_name = _file_name(record)
    if record.event_id == DETECTED:
        return f"Defender detected {name}" + (f" in {file_name}" if file_name else "")
    suffix = f" ({file_name})" if file_name else ""
    if record.event_id in ACTION_FAILED:
        return f"Defender could not act on {name}{suffix}"
    return f"Defender {ACTION_VERBS[removing_action(record) or 'none']} {name}{suffix}"


def _file_name(record: WindowsEvent) -> str | None:
    path = file_path_of(record)
    return None if path is None else ecs.base_name(path)


def _rule(record: WindowsEvent) -> dict[str, Any]:
    rule: dict[str, Any] = {
        "id": text_of(record, "Threat ID"),
        "name": text_of(record, "Threat Name"),
        "ruleset": RULESET,
    }
    if record.event_id == DETECTED:
        rule["description"] = text_of(record, "Category Name")
        rule["reference"] = _present_list(text_of(record, "FWLink"))
    return _present(rule)


def _sections(record: WindowsEvent, detection: Detection, analysis_id: int) -> dict[str, Any]:
    sections: dict[str, Any] = {}
    if (path := file_path_of(record)) is not None:
        sections["file"] = ecs.file_fields(path)
    if detection.scope is Scope.DROPPED and (process := text_of(record, "Process Name")):
        sections["process"] = {"executable": process, "name": ecs.base_name(process)}
    if user := _user(record):
        sections["user"] = user
    if record.event_id in ACTION_FAILED:
        sections["error"] = _present(
            {"code": text_of(record, "Error Code"), "message": text_of(record, "Error Description")}
        )
    if (related := _linked_detection(record, detection, analysis_id)) is not None:
        sections["related"] = related
    return sections


def _user(record: WindowsEvent) -> dict[str, str] | None:
    field = "Detection User" if record.event_id == DETECTED else "Remediation User"
    account = text_of(record, field)
    if account is None:
        return None
    domain, separator, name = account.partition("\\")
    return {"domain": domain, "name": name} if separator else {"name": account}


def _linked_detection(
    record: WindowsEvent, detection: Detection, analysis_id: int
) -> dict[str, Any] | None:
    detected = detection.detected
    if record.event_id == DETECTED or detected is None or detected.record_id is None:
        return None
    detected_id = ecs.event_id(analysis_id, SOURCE, SOURCE_FILE, detected.record_id)
    return related_events(detected_id)


def _tartarus(
    record: WindowsEvent, detection: Detection, on_snapshot_clock: bool
) -> dict[str, Any]:
    tartarus: dict[str, Any] = {
        "defender": _present(
            {
                "detection_id": detection.detection_id,
                "scope": detection.scope.value,
                "action_id": int_of(record, "Action ID"),
                "category_id": int_of(record, "Category ID"),
                "state": int_of(record, "State"),
                "status_code": int_of(record, "Status Code"),
                "clock": "snapshot" if on_snapshot_clock else None,
            }
        )
    }
    if record.event_id == DETECTED and (match := _match(record)) is not None:
        tartarus["detection"] = {"match": match}
    return tartarus


def _match(record: WindowsEvent) -> str | None:
    pieces = (
        f"{label}: {value}"
        for label, value in (
            ("path", text_of(record, "Path")),
            ("process", text_of(record, "Process Name")),
        )
        if value
    )
    return detection_match(pieces)


def _raw(record: WindowsEvent) -> dict[str, Any]:
    return {
        "EventID": record.event_id,
        "EventRecordID": record.record_id,
        "SystemTime": None
        if record.system_time is None
        else ecs.format_timestamp(record.system_time),
        "Data": dict(record.data),
    }


def _present(fields: Mapping[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in fields.items() if value is not None}


def _present_list(value: str | None) -> list[str] | None:
    return None if value is None else [value]
