"""The body of `POST events/search` and the page its response becomes."""

from collections.abc import Mapping
from typing import Any

from app.events.columns import resolve_columns
from app.events.cursor import SortValue, decode_cursor, encode_cursor
from app.events.event_model import EVENT_SOURCE_FIELDS, event_from_source
from app.events.execution import SEARCH_TIMEOUT
from app.events.filters import filter_query
from app.schemas.events_api import EventPage, SearchRequest
from app.views.event_fields import WITHOUT_RAW, hits_of, total_of

SORT_KEYS = ("@timestamp", "event.sequence", "event.id")
OLDEST_FIRST: list[dict[str, str]] = [{key: "asc"} for key in SORT_KEYS]


def build_search_body(request: SearchRequest) -> dict[str, Any]:
    """Sorts by time, then sequence, then id. The ingester numbers events uniquely, but the id
    keeps the order total even if two events share a time and a sequence, which is what
    `search_after` needs to reach each event exactly once.

    One more event than the page is fetched, to know whether a next page exists.
    """
    body: dict[str, Any] = {
        "query": filter_query(request),
        "sort": _sort(request),
        "size": request.size + 1,
        "track_total_hits": True,
        "timeout": SEARCH_TIMEOUT,
        "_source": _source(resolve_columns(request.columns)),
    }
    if request.search_after is not None:
        body["search_after"] = decode_cursor(request.search_after, request.sort)
    return body


def _source(columns: list[str]) -> dict[str, list[str]]:
    if not columns:
        return WITHOUT_RAW
    return {"includes": [*EVENT_SOURCE_FIELDS, *columns]}


def _sort(request: SearchRequest) -> list[dict[str, str]]:
    order = "desc" if request.sort.startswith("-") else "asc"
    return [{key: order} for key in SORT_KEYS]


def read_search_response(request: SearchRequest, response: Mapping[str, Any]) -> EventPage:
    hits: list[Mapping[str, Any]] = response["hits"]["hits"]
    page = hits[: request.size]
    columns = resolve_columns(request.columns)
    return EventPage(
        events=[event_from_source(source, columns) for source in hits_of({"hits": {"hits": page}})],
        total=total_of(response),
        next_cursor=_cursor_after(request, page) if len(hits) > request.size else None,
    )


def _cursor_after(request: SearchRequest, page: list[Mapping[str, Any]]) -> str:
    last_sort: list[SortValue] = page[-1]["sort"]
    return encode_cursor(request.sort, last_sort)
