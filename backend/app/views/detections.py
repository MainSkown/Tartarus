from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from itertools import islice

from app.analyses.summary import SEVERITY_ORDER
from app.schemas.views_findings import Detection, DetectionGroup, DetectionsView, RelatedEvent
from app.search.index import EventIndex
from app.views.alerts import search_alerts
from app.views.event_fields import (
    Source,
    event_id,
    event_time,
    hits_of,
    int_at,
    process_ref,
    severity_name,
    text_at,
    texts_at,
)

RELATED_PER_DETECTION = 50
MAX_RELATED_LOOKUP = 10_000
RULESET_ORDER = ("sigma", "cape", "yara", "suricata", "defender", "volatility")
UNKNOWN_RULESET = "unknown"
ALERT_FIELDS = (
    "event.id",
    "event.severity",
    "@timestamp",
    "rule",
    "threat.technique.id",
    "related.events",
    "process",
    "tartarus.detection.match",
)
RELATED_FIELDS = (
    "event.id",
    "event.action",
    "@timestamp",
    "tartarus.lane",
    "tartarus.summary",
    "process.pid",
    "process.name",
)


@dataclass(frozen=True)
class _Alert:
    source: Source
    related_ids: list[str]

    @property
    def shown_related_ids(self) -> list[str]:
        return self.related_ids[:RELATED_PER_DETECTION]


async def list_detections(index: EventIndex, analysis_id: int) -> DetectionsView:
    found = await search_alerts(index, analysis_id, ALERT_FIELDS)
    alerts = [_Alert(source, texts_at(source, "related", "events")) for source in found.alerts]
    related = await _resolve_related(index, analysis_id, alerts)
    detections = [_detection(alert, related) for alert in alerts]
    return DetectionsView(groups=_grouped(detections), total=found.total)


async def _resolve_related(
    index: EventIndex, analysis_id: int, alerts: Iterable[_Alert]
) -> dict[str, RelatedEvent]:
    wanted = dict.fromkeys(i for alert in alerts for i in alert.shown_related_ids)
    ids = list(islice(wanted, MAX_RELATED_LOOKUP))
    if not ids:
        return {}
    response = await index.search(
        analysis_id,
        {
            "size": len(ids),
            "query": {"terms": {"event.id": ids}},
            "_source": {"includes": list(RELATED_FIELDS)},
        },
    )
    return {event_id(source): _related_event(source) for source in hits_of(response)}


def _related_event(source: Source) -> RelatedEvent:
    return RelatedEvent(
        id=event_id(source),
        time=event_time(source),
        lane=text_at(source, "tartarus", "lane") or "",
        action=text_at(source, "event", "action") or "",
        summary=text_at(source, "tartarus", "summary") or "",
        process=process_ref(source),
    )


def _detection(alert: _Alert, related: Mapping[str, RelatedEvent]) -> Detection:
    source = alert.source
    events = [related[i] for i in alert.shown_related_ids if i in related]
    return Detection(
        id=event_id(source),
        name=text_at(source, "rule", "name") or event_id(source),
        description=text_at(source, "rule", "description"),
        severity=severity_name(int_at(source, "event", "severity") or 0),
        ruleset=text_at(source, "rule", "ruleset") or UNKNOWN_RULESET,
        techniques=texts_at(source, "threat", "technique", "id"),
        match=text_at(source, "tartarus", "detection", "match"),
        references=texts_at(source, "rule", "reference"),
        author=", ".join(texts_at(source, "rule", "author")) or None,
        time=event_time(source),
        process=process_ref(source) or next((e.process for e in events if e.process), None),
        related_events=events,
        related_event_total=len(alert.related_ids),
    )


def _grouped(detections: list[Detection]) -> list[DetectionGroup]:
    by_ruleset: dict[str, list[Detection]] = {}
    for detection in sorted(detections, key=_most_severe_first):
        by_ruleset.setdefault(detection.ruleset, []).append(detection)
    return [
        DetectionGroup(ruleset=ruleset, detections=by_ruleset[ruleset])
        for ruleset in sorted(by_ruleset, key=_ruleset_position)
    ]


def _most_severe_first(detection: Detection) -> tuple[int, str]:
    return (-SEVERITY_ORDER.index(detection.severity), detection.name.lower())


def _ruleset_position(ruleset: str) -> tuple[int, str]:
    known = RULESET_ORDER.index(ruleset) if ruleset in RULESET_ORDER else len(RULESET_ORDER)
    return (known, ruleset)
