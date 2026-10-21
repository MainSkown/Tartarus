from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from app.schemas.views_findings import IocType
from app.search.index import analysis_id_of_index
from app.views.iocs import EVENT_IOCS, EventIoc

ANALYSES_PER_PIVOT = 1000

# Hashes are listed from the report in the IOC view; only file events carry them in the index.
_PIVOTABLE = {
    **{spec.type: spec for spec in EVENT_IOCS},
    IocType.HASH: EventIoc(IocType.HASH, "file.hash.sha256", lane="file"),
}


class UnpivotableIocError(Exception):
    """Raised for an IOC kind that no event field holds, so no analysis can be found by it."""


class AllAnalysesSearch(Protocol):
    async def search_all(self, body: dict[str, Any]) -> dict[str, Any]: ...


@dataclass(frozen=True)
class AnalysisHits:
    analysis_id: int
    count: int


async def analyses_containing(
    index: AllAnalysesSearch, kind: IocType, value: str
) -> list[AnalysisHits]:
    """The analyses with events holding the IOC value, those with the most events first."""
    spec = _PIVOTABLE.get(kind)
    if spec is None:
        raise UnpivotableIocError(f"{kind.value} indicators are not stored in events")
    response = await index.search_all(
        {
            "size": 0,
            "query": _query(spec, value),
            "aggs": {"analyses": {"terms": {"field": "_index", "size": ANALYSES_PER_PIVOT}}},
        }
    )
    buckets = response.get("aggregations", {}).get("analyses", {}).get("buckets", [])
    hits = [_hits(bucket) for bucket in buckets]
    return sorted(hits, key=lambda hit: (-hit.count, -hit.analysis_id))


def _query(spec: EventIoc, value: str) -> dict[str, Any]:
    scope = spec.query["bool"]
    return {
        "bool": {
            "filter": [*scope["filter"], {"term": {spec.field: value}}],
            "must_not": scope["must_not"],
        }
    }


def _hits(bucket: Mapping[str, Any]) -> AnalysisHits:
    return AnalysisHits(analysis_id_of_index(str(bucket["key"])), int(bucket["doc_count"]))
