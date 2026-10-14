from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.annotations.read import load_event_annotations
from app.api.dependencies import get_event_index, require_analysis
from app.db.session import get_session
from app.events.execution import run_search
from app.events.facets import build_facets_body, read_facets_response
from app.events.search import build_search_body, read_search_response
from app.events.service import load_event_detail, load_histogram
from app.schemas.events_api import (
    EventDetail,
    EventPage,
    FacetsRequest,
    FacetsResponse,
    Histogram,
    HistogramRequest,
    SearchRequest,
)
from app.search.index import EventIndex

router = APIRouter(prefix="/analyses", tags=["events"])

Session = Annotated[AsyncSession, Depends(get_session)]
Events = Annotated[EventIndex, Depends(get_event_index)]


@router.post("/{analysis_id}/events/search")
async def search(
    analysis_id: int, request: SearchRequest, session: Session, events: Events
) -> EventPage:
    """One page of the analysis's events matching the query, the chips and the other filters.

    Sorted by time, then by the event's own order, then by id, so the order is total. `total`
    is exact; `next_cursor` is opaque, null on the last page, and goes back as `search_after`
    for the next one. `columns` adds those catalog fields to each event's `fields`. `422` for a
    query or chip that does not compile (its `error.details.errors` lists each problem with its
    span), a malformed cursor or a column that cannot be shown (`invalid_column`). An analysis
    with no events yet answers with an empty page.
    """
    await require_analysis(session, analysis_id)
    body = build_search_body(request)
    return read_search_response(request, await run_search(events, analysis_id, body))


@router.post("/{analysis_id}/events/facets")
async def facets(
    analysis_id: int, request: FacetsRequest, session: Session, events: Events
) -> FacetsResponse:
    """The ten most common values of each requested field, and how many events have a value
    for it, over the events the filter keeps, except that a facet ignores the chips on its own
    field so the other values of a field already narrowed stay visible.

    Fields are catalog names or aliases; a text, flat-object or unsearchable field, a composite
    alias such as `domain` and an unknown field are refused with `422`.
    """
    await require_analysis(session, analysis_id)
    body = build_facets_body(request)
    return read_facets_response(request.fields, await run_search(events, analysis_id, body))


@router.post("/{analysis_id}/events/histogram")
async def histogram(
    analysis_id: int, request: HistogramRequest, session: Session, events: Events
) -> Histogram:
    """Event counts per time bucket, split by lane, and the detections, for the timeline.

    `interval` is `auto` (the smallest of 1, 2, 5, ... ms, s, min, h, days that makes at most 120
    buckets) or milliseconds, widened where needed to keep to 2000 buckets. The buckets are
    contiguous from the one holding `from` to the one holding `to` (the time range where it names
    an end, else the first and last matching event), empty ones included, so they sum to `total`.
    `detections` are the matching alerts, at most 500, oldest first.
    """
    await require_analysis(session, analysis_id)
    return await load_histogram(events, analysis_id, request)


@router.get("/{analysis_id}/events/{event_id:path}")
async def detail(analysis_id: int, event_id: str, session: Session, events: Events) -> EventDetail:
    """One event: its typed fields, its whole stored document (`source`, with the raw record
    that searches leave out) and `related`.

    `related.references` are the events this one names as its triggers (a detection's
    `related.events`); `related.referenced_by` are the detections that name this one. Each
    lists at most 50 and counts them all. The id may contain slashes and colons, encoded or not.
    `annotations` are the analyst's tags and notes on this event. `404` for an unknown analysis
    or event.
    """
    await require_analysis(session, analysis_id)
    found = await load_event_detail(events, analysis_id, event_id)
    if found is None:
        raise HTTPException(404, f"Event {event_id} not found in analysis {analysis_id}")
    annotations = await load_event_annotations(session, analysis_id, found.event.id)
    return found.model_copy(update={"annotations": annotations})
