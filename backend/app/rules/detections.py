import copy
from collections.abc import Mapping
from datetime import datetime
from typing import Any

from app.analyses.summary import SEVERITY_ORDER
from app.db.models.analysis import Severity
from app.ingest.ecs import (
    LANES,
    EventFactory,
    EventShape,
    Phase,
    SourceRecord,
    detection_match,
    related_events,
)
from app.ingest.protocol import IngestContext
from app.rules.attack import attack_fields
from app.rules.predicate import Event
from app.rules.rule import Rule

SOURCE = "sigma"
DATASET = "sigma.rule"
ACTION = "rule-matched"
FALLBACK_LANE = "process"
DEFAULT_LEVEL = Severity.MEDIUM
SEVERITY_BY_LEVEL = {
    "informational": Severity.INFO,
    "low": Severity.LOW,
    "medium": Severity.MEDIUM,
    "high": Severity.HIGH,
    "critical": Severity.CRITICAL,
}


def event_time(event: Event) -> datetime | None:
    """The event's `@timestamp` as an aware datetime, or `None` if it has none that parses."""
    text = event.get("@timestamp")
    if not isinstance(text, str):
        return None
    try:
        moment = datetime.fromisoformat(text)
    except ValueError:
        return None
    return moment if moment.tzinfo else None


def event_id_of(event: Event) -> str | None:
    section = event.get("event")
    identifier = section.get("id") if isinstance(section, Mapping) else None
    return identifier if isinstance(identifier, str) and identifier else None


def entity_id_of(event: Event) -> str | None:
    process = event.get("process")
    entity = process.get("entity_id") if isinstance(process, Mapping) else None
    return entity if isinstance(entity, str) else None


class DetectionBuilder:
    """Builds the `event.kind: alert` document for a rule matching an event."""

    def __init__(self, context: IngestContext, phase: Phase) -> None:
        self._factory = EventFactory(
            context, source=SOURCE, source_file="rule", module=SOURCE, phase=phase
        )

    def build(
        self, rule: Rule, trigger: Event, trigger_id: str, moment: datetime
    ) -> dict[str, Any]:
        lane = _lane_of(trigger)
        # The id is the factory's sha1 over (analysis, source, "rule|trigger", 0): one alert per
        # (rule, triggering event), the same in the live run and the final ingest.
        record = SourceRecord(
            0, moment, _raw(rule, trigger_id), source_file=f"{rule.id}|{trigger_id}"
        )
        sections: dict[str, Any] = {
            "rule": _rule_section(rule),
            "related": related_events(trigger_id),
        }
        if (attack := attack_fields(rule.tags)).techniques or attack.tactics:
            sections["threat"] = _threat_section(attack.techniques, attack.tactics)
        if isinstance(process := trigger.get("process"), Mapping):
            sections["process"] = copy.deepcopy(dict(process))
        match = _match_text(rule, trigger)
        tartarus = {"detection": {"match": match}} if match else None
        shape = EventShape(ACTION, ("intrusion_detection",), ("info",), lane, DATASET, "alert")
        return self._factory.build(
            shape,
            record,
            rule.title,
            severity=SEVERITY_ORDER.index(SEVERITY_BY_LEVEL.get(rule.level or "", DEFAULT_LEVEL)),
            tartarus=tartarus,
            **sections,
        )


def _match_text(rule: Rule, trigger: Event) -> str | None:
    pieces = rule.explain(trigger) if rule.explain else []
    return detection_match(pieces) or rule.condition


def _lane_of(trigger: Event) -> str:
    section = trigger.get("tartarus")
    lane = section.get("lane") if isinstance(section, Mapping) else None
    return lane if isinstance(lane, str) and lane in LANES else FALLBACK_LANE


def _raw(rule: Rule, trigger_id: str) -> dict[str, Any]:
    return {
        "level": rule.level,
        "status": rule.status,
        "tags": list(rule.tags),
        "triggering_event": trigger_id,
    }


def _rule_section(rule: Rule) -> dict[str, Any]:
    section: dict[str, Any] = {"id": rule.id, "name": rule.title, "ruleset": "sigma"}
    if rule.description:
        section["description"] = rule.description
    if rule.references:
        section["reference"] = list(rule.references)
    return section


def _threat_section(techniques: list[str], tactics: list[str]) -> dict[str, Any]:
    section: dict[str, Any] = {}
    if techniques:
        section["technique"] = {"id": techniques}
    if tactics:
        section["tactic"] = {"name": tactics}
    return section
