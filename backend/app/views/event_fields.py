"""Readers for event documents as the index returns them (`_source`)."""

from collections.abc import Mapping
from datetime import datetime
from typing import Any

from app.analyses.summary import SEVERITY_ORDER
from app.db.models.analysis import Severity
from app.ingest.reading import text_or_none, to_int
from app.schemas.views_events import ProcessRef

type Source = Mapping[str, Any]

TIME_ORDER: list[dict[str, str]] = [{"@timestamp": "asc"}, {"event.sequence": "asc"}]
WITHOUT_RAW = {"excludes": ["tartarus.raw"]}


def dig(source: Source, *path: str) -> Any:
    value: Any = source
    for step in path:
        if not isinstance(value, Mapping):
            return None
        value = value.get(step)
    return value


def text_at(source: Source, *path: str) -> str | None:
    return text_or_none(dig(source, *path))


def int_at(source: Source, *path: str) -> int | None:
    return to_int(dig(source, *path))


def texts_at(source: Source, *path: str) -> list[str]:
    value = dig(source, *path)
    items = value if isinstance(value, list) else [value]
    return [item for item in items if isinstance(item, str) and item]


def parse_time(text: str | None) -> datetime | None:
    return None if text is None else datetime.fromisoformat(text)


def event_time(source: Source) -> datetime:
    return datetime.fromisoformat(str(source["@timestamp"]))


def event_id(source: Source) -> str:
    return str(source["event"]["id"])


def process_ref(source: Source) -> ProcessRef | None:
    pid = int_at(source, "process", "pid")
    return None if pid is None else ProcessRef(pid=pid, name=text_at(source, "process", "name"))


def severity_name(level: int) -> Severity:
    return SEVERITY_ORDER[max(0, min(level, len(SEVERITY_ORDER) - 1))]


def hits_of(response: Mapping[str, Any]) -> list[Source]:
    return [hit["_source"] for hit in response["hits"]["hits"]]


def total_of(response: Mapping[str, Any]) -> int:
    return int(response["hits"]["total"]["value"])
