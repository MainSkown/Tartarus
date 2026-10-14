"""Endpoints that take several searches to answer."""

import asyncio
from typing import Any

from app.events.detail import (
    find_body,
    read_detail,
    referenced_by_body,
    references_body,
    related_ids,
)
from app.events.execution import run_search
from app.events.histogram import (
    detections_body,
    extent_body,
    histogram_body,
    plan_histogram,
    read_detections,
    read_extent,
    read_histogram,
)
from app.schemas.events_api import EventDetail, Histogram, HistogramRequest
from app.search.index import EventIndex

NO_HITS = {"hits": {"total": {"value": 0}, "hits": []}, "aggregations": {}}


async def load_histogram(
    index: EventIndex, analysis_id: int, request: HistogramRequest
) -> Histogram:
    """The span first, since the interval depends on it; the detections beside it."""
    extent_response, detections_response = await asyncio.gather(
        run_search(index, analysis_id, extent_body(request)),
        run_search(index, analysis_id, detections_body(request)),
    )
    plan = plan_histogram(request, read_extent(extent_response))
    detections = read_detections(detections_response)
    if not plan.bucket_keys():
        return read_histogram(plan, NO_HITS, detections)
    response = await run_search(index, analysis_id, histogram_body(request, plan))
    return read_histogram(plan, response, detections)


async def load_event_detail(
    index: EventIndex, analysis_id: int, event_id: str
) -> EventDetail | None:
    """The event with the events it names and the ones that name it; None for an unknown id."""
    found = await run_search(index, analysis_id, find_body(event_id))
    hits = found["hits"]["hits"]
    if not hits:
        return None
    source = hits[0]["_source"]
    named = related_ids(source)
    references, referenced_by = await asyncio.gather(
        run_search(index, analysis_id, references_body(named)) if named else _nothing(),
        run_search(index, analysis_id, referenced_by_body(event_id)),
    )
    return read_detail(source, references, referenced_by)


async def _nothing() -> dict[str, Any]:
    return NO_HITS
