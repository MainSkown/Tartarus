from collections.abc import Sequence

from app.schemas.events_api import Event, EventDestination, EventProcess, JsonValue
from app.views.event_fields import (
    Source,
    dig,
    event_id,
    event_time,
    int_at,
    severity_name,
    text_at,
    texts_at,
)

EVENT_SOURCE_FIELDS = [
    "@timestamp",
    "event.id",
    "event.sequence",
    "event.kind",
    "event.category",
    "event.action",
    "event.module",
    "event.dataset",
    "event.severity",
    "tartarus.lane",
    "tartarus.summary",
    "process.pid",
    "process.name",
    "process.entity_id",
    "api.name",
    "rule.name",
    "rule.ruleset",
    "destination.ip",
    "destination.port",
    "destination.domain",
    "dns.question.name",
    "url.full",
    "file.path",
    "registry.path",
]


def event_from_source(source: Source, columns: Sequence[str] = ()) -> Event:
    """`columns` are canonical field names; those the document has a value for fill `fields`."""
    severity = int_at(source, "event", "severity")
    return Event(
        id=event_id(source),
        time=event_time(source),
        sequence=int_at(source, "event", "sequence"),
        lane=text_at(source, "tartarus", "lane"),
        kind=text_at(source, "event", "kind"),
        category=texts_at(source, "event", "category"),
        action=text_at(source, "event", "action"),
        module=text_at(source, "event", "module"),
        dataset=text_at(source, "event", "dataset"),
        summary=text_at(source, "tartarus", "summary"),
        severity=None if severity is None else severity_name(severity),
        process=_process(source),
        api_name=text_at(source, "api", "name"),
        rule_name=text_at(source, "rule", "name"),
        rule_ruleset=text_at(source, "rule", "ruleset"),
        destination=_destination(source),
        dns_query=text_at(source, "dns", "question", "name"),
        url=text_at(source, "url", "full"),
        file_path=text_at(source, "file", "path"),
        registry_path=text_at(source, "registry", "path"),
        fields=_columns(source, columns),
    )


def _columns(source: Source, columns: Sequence[str]) -> dict[str, JsonValue]:
    values = {column: dig(source, *column.split(".")) for column in columns}
    return {column: value for column, value in values.items() if value is not None}


def _process(source: Source) -> EventProcess | None:
    process = EventProcess(
        pid=int_at(source, "process", "pid"),
        name=text_at(source, "process", "name"),
        entity_id=text_at(source, "process", "entity_id"),
    )
    return process if process != EventProcess(pid=None, name=None, entity_id=None) else None


def _destination(source: Source) -> EventDestination | None:
    destination = EventDestination(
        ip=text_at(source, "destination", "ip"),
        port=int_at(source, "destination", "port"),
        domain=text_at(source, "destination", "domain"),
    )
    return destination if destination != EventDestination(ip=None, port=None, domain=None) else None
