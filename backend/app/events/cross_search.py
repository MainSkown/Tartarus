"""Searching the events of every analysis at once, each event labelled with its analysis."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from app.events.columns import resolve_columns
from app.events.cursor import SortValue, decode_cursor, encode_cursor
from app.events.event_model import event_from_source
from app.events.execution import run_search_all
from app.events.search import build_search_body
from app.schemas.events_api import Event, SearchRequest
from app.search.index import EventIndex, analysis_id_of_index
from app.views.event_fields import total_of

# Time, sequence and id are only unique within one analysis, so the index closes the order.
CROSS_SORT_VALUE_SHAPE = (int, int, str, str)


@dataclass(frozen=True, slots=True)
class CrossSearchHit:
    analysis_id: int
    event: Event


@dataclass(frozen=True, slots=True)
class CrossSearchPage:
    events: list[CrossSearchHit]
    total: int
    next_cursor: str | None


async def search_across_analyses(index: EventIndex, request: SearchRequest) -> CrossSearchPage:
    """The events of every analysis matching the request, paged by `search_after` in one total
    order; a query that does not compile is a 422 before anything is searched."""
    response = await run_search_all(index, _cross_search_body(request))
    return _read_page(request, response)


def _cross_search_body(request: SearchRequest) -> dict[str, Any]:
    body = build_search_body(request.model_copy(update={"search_after": None}))
    order = "desc" if request.sort.startswith("-") else "asc"
    body["sort"] = [*body["sort"], {"_index": order}]
    if request.search_after is not None:
        body["search_after"] = decode_cursor(
            request.search_after, request.sort, CROSS_SORT_VALUE_SHAPE
        )
    return body


def _read_page(request: SearchRequest, response: Mapping[str, Any]) -> CrossSearchPage:
    hits: list[Mapping[str, Any]] = response["hits"]["hits"]
    page = hits[: request.size]
    columns = resolve_columns(request.columns)
    return CrossSearchPage(
        events=[
            CrossSearchHit(
                analysis_id=analysis_id_of_index(hit["_index"]),
                event=event_from_source(hit["_source"], columns),
            )
            for hit in page
        ],
        total=total_of(response),
        next_cursor=_cursor_after(request, page) if len(hits) > request.size else None,
    )


def _cursor_after(request: SearchRequest, page: list[Mapping[str, Any]]) -> str:
    last_sort: list[SortValue] = page[-1]["sort"]
    return encode_cursor(request.sort, last_sort)
