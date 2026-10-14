"""Which events a report lists: the ones that explain the run, not the thousands that fill it."""

from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from app.db.models.analysis import Severity
from app.schemas.events_api import Event
from app.schemas.views_findings import Detection, RelatedEvent

MAX_KEY_EVENTS = 200
CITED_PER_DETECTION = 5
ALERT_LANE = "alert"


class KeyEventReason(StrEnum):
    """Why an event is listed; the members are in the order the cap spares them."""

    ALERT = "alert"
    PROCESS = "process"
    FILE_OR_REGISTRY = "file-registry"
    CITED = "cited"
    NETWORK = "network"


class EventFacts(BaseModel):
    """What the report shows of an event; `destination` is only set for network events."""

    model_config = ConfigDict(frozen=True)

    id: str
    time: datetime
    sequence: int | None
    lane: str
    action: str | None
    summary: str
    severity: Severity | None
    process_name: str | None
    pid: int | None
    destination: str | None = None

    def order(self) -> tuple[datetime, int, str]:
        return (self.time, self.sequence or 0, self.id)


class KeyEvent(EventFacts):
    reason: KeyEventReason


@dataclass(frozen=True)
class Citation:
    """The events one detection cites, as far as the detections view lists them, and how many
    it cites in all.
    """

    detection_id: str
    events: Sequence[EventFacts]
    total: int

    @property
    def shown(self) -> tuple[EventFacts, ...]:
        return tuple(sorted(self.events, key=EventFacts.order)[:CITED_PER_DETECTION])

    @property
    def more(self) -> int:
        return max(self.total - len(self.shown), 0)


@dataclass(frozen=True)
class KeyEventCandidates:
    """The events each rung may take from, in any order."""

    alerts: Sequence[EventFacts] = ()
    process: Sequence[EventFacts] = ()
    file_and_registry: Sequence[EventFacts] = ()
    citations: Sequence[Citation] = ()
    network: Sequence[EventFacts] = ()

    def by_rung(self) -> Iterator[tuple[KeyEventReason, list[EventFacts]]]:
        yield KeyEventReason.ALERT, _earliest_first(self.alerts)
        yield KeyEventReason.PROCESS, _earliest_first(self.process)
        yield KeyEventReason.FILE_OR_REGISTRY, _earliest_first(self.file_and_registry)
        yield (
            KeyEventReason.CITED,
            _earliest_first(event for citation in self.citations for event in citation.shown),
        )
        yield KeyEventReason.NETWORK, _first_per_destination(self.network)


class KeyEvents(BaseModel):
    model_config = ConfigDict(frozen=True)

    events: tuple[KeyEvent, ...] = ()
    cut: int = 0
    more_cited: dict[str, int] = Field(default_factory=dict)


def select_key_events(candidates: KeyEventCandidates, cap: int = MAX_KEY_EVENTS) -> KeyEvents:
    """At most `cap` events in time order. An alert beats a process event beats a file or
    registry event beats a cited event beats a network event; an event keeps the reason of the
    first rung that offered it, and `cut` counts the distinct events the cap left out.
    """
    considered: set[str] = set()
    chosen: list[KeyEvent] = []
    cut = 0
    for reason, events in candidates.by_rung():
        for facts in events:
            if facts.id in considered:
                continue
            considered.add(facts.id)
            if len(chosen) < cap:
                chosen.append(KeyEvent(**facts.model_dump(), reason=reason))
            else:
                cut += 1
    return KeyEvents(
        events=tuple(sorted(chosen, key=EventFacts.order)),
        cut=cut,
        more_cited={
            citation.detection_id: citation.more
            for citation in candidates.citations
            if citation.more
        },
    )


def _earliest_first(events: Iterator[EventFacts] | Sequence[EventFacts]) -> list[EventFacts]:
    return sorted(events, key=EventFacts.order)


def _first_per_destination(events: Sequence[EventFacts]) -> list[EventFacts]:
    first: dict[str, EventFacts] = {}
    for facts in _earliest_first(events):
        if facts.destination is not None:
            first.setdefault(facts.destination, facts)
    return list(first.values())


def facts_from_event(event: Event) -> EventFacts:
    return EventFacts(
        id=event.id,
        time=event.time,
        sequence=event.sequence,
        lane=event.lane or "",
        action=event.action,
        summary=event.summary or "",
        severity=event.severity,
        process_name=event.process.name if event.process else None,
        pid=event.process.pid if event.process else None,
        destination=_destination(event),
    )


def facts_from_detection(detection: Detection) -> EventFacts:
    return EventFacts(
        id=detection.id,
        time=detection.time,
        sequence=None,
        lane=ALERT_LANE,
        action=None,
        summary=detection.name,
        severity=detection.severity,
        process_name=detection.process.name if detection.process else None,
        pid=detection.process.pid if detection.process else None,
    )


def facts_from_related(related: RelatedEvent) -> EventFacts:
    return EventFacts(
        id=related.id,
        time=related.time,
        sequence=None,
        lane=related.lane,
        action=related.action,
        summary=related.summary,
        severity=None,
        process_name=related.process.name if related.process else None,
        pid=related.process.pid if related.process else None,
    )


def _destination(event: Event) -> str | None:
    return (
        event.dns_query
        or (event.destination.domain if event.destination else None)
        or (event.destination.ip if event.destination else None)
        or event.url
    )
