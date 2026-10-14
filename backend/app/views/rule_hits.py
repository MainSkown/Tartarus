from collections.abc import Mapping
from typing import Any

from app.search.index import EventIndex

MAX_RULES = 10_000


def _sigma_hits_body() -> dict[str, Any]:
    return {
        "size": 0,
        "query": {
            "bool": {
                "filter": [{"term": {"event.kind": "alert"}}, {"term": {"rule.ruleset": "sigma"}}]
            }
        },
        "aggs": {"rules": {"terms": {"field": "rule.id", "size": MAX_RULES}}},
    }


async def hits_in_analysis(index: EventIndex, analysis_id: int) -> dict[str, int]:
    """Sigma detections per rule id in one analysis; ids come back as the index stores them,
    which is lower case."""
    return _counts(await index.search(analysis_id, _sigma_hits_body()))


async def hits_across_analyses(index: EventIndex) -> dict[str, int]:
    """Sigma detections per rule id over every analysis, in one aggregation."""
    return _counts(await index.search_all(_sigma_hits_body()))


def _counts(response: Mapping[str, Any]) -> dict[str, int]:
    buckets = response.get("aggregations", {}).get("rules", {}).get("buckets", [])
    return {str(bucket["key"]): int(bucket["doc_count"]) for bucket in buckets}
