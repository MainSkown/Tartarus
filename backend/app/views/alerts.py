from collections.abc import Sequence
from dataclasses import dataclass

from app.search.index import EventIndex
from app.views.event_fields import TIME_ORDER, Source, hits_of, total_of

MAX_ALERTS = 1000


@dataclass(frozen=True)
class AlertSearch:
    alerts: list[Source]
    total: int


async def search_alerts(
    index: EventIndex, analysis_id: int, source_fields: Sequence[str]
) -> AlertSearch:
    """The analysis's detections, earliest first; `total` counts alerts beyond `MAX_ALERTS` too."""
    response = await index.search(
        analysis_id,
        {
            "size": MAX_ALERTS,
            "track_total_hits": True,
            "query": {"term": {"event.kind": "alert"}},
            "sort": TIME_ORDER,
            "_source": {"includes": list(source_fields)},
        },
    )
    return AlertSearch(hits_of(response), total_of(response))
