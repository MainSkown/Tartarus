from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.dependencies import get_event_index
from app.events.cross_search import search_across_analyses
from app.schemas.events_api import CrossSearchEvent, CrossSearchResponse, SearchRequest
from app.search.index import EventIndex

router = APIRouter(tags=["search"])

Events = Annotated[EventIndex, Depends(get_event_index)]


@router.post("/search")
async def across_analyses(request: SearchRequest, events: Events) -> CrossSearchResponse:
    """One page of the events of every analysis matching the query, the chips and the other
    filters, each labelled with its `analysis_id`.

    Same filter, sort and cursor rules as an analysis's own event search, with the analysis
    order closing ties. `422` for a query or chip that does not compile.
    """
    page = await search_across_analyses(events, request)
    return CrossSearchResponse(
        events=[
            CrossSearchEvent(analysis_id=hit.analysis_id, event=hit.event) for hit in page.events
        ],
        total=page.total,
        next_cursor=page.next_cursor,
    )
