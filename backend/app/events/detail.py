"""The searches of `GET events/{id}` and the detail their responses become."""

from collections.abc import Mapping
from typing import Any

from app.events.event_model import event_from_source
from app.events.execution import SEARCH_TIMEOUT
from app.events.search import OLDEST_FIRST
from app.query.clauses import lowercase_like_index
from app.schemas.events_api import Event, EventDetail, RelatedEvents
from app.schemas.views_events import Listing
from app.views.event_fields import WITHOUT_RAW, Source, hits_of, texts_at, total_of

MAX_RELATED = 50
MAX_NAMED_IDS = 1000


def find_body(event_id: str) -> dict[str, Any]:
    return {"query": {"ids": {"values": [event_id]}}, "size": 1, "timeout": SEARCH_TIMEOUT}


def related_ids(source: Source) -> list[str]:
    return texts_at(source, "related", "events")[:MAX_NAMED_IDS]


def references_body(event_ids: list[str]) -> dict[str, Any]:
    return _related_body({"ids": {"values": event_ids}})


def referenced_by_body(event_id: str) -> dict[str, Any]:
    named = {"term": {"related.events": lowercase_like_index(event_id)}}
    return _related_body({"bool": {"filter": [named]}})


def _related_body(query: dict[str, Any]) -> dict[str, Any]:
    return {
        "query": query,
        "size": MAX_RELATED,
        "sort": OLDEST_FIRST,
        "track_total_hits": True,
        "timeout": SEARCH_TIMEOUT,
        "_source": WITHOUT_RAW,
    }


def read_detail(
    source: Source, references: Mapping[str, Any], referenced_by: Mapping[str, Any]
) -> EventDetail:
    return EventDetail(
        event=event_from_source(source),
        source=dict(source),
        related=RelatedEvents(
            references=_listing(references), referenced_by=_listing(referenced_by)
        ),
    )


def _listing(response: Mapping[str, Any]) -> Listing[Event]:
    return Listing[Event](
        items=[event_from_source(source) for source in hits_of(response)],
        total=total_of(response),
    )
