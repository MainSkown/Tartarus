"""The body of `POST events/facets` and the facets its response becomes."""

from collections.abc import Mapping
from typing import Any

from app.errors import ApiError
from app.events.aggregatable import resolve_for_aggregation
from app.events.execution import SEARCH_TIMEOUT
from app.events.filters import filter_query
from app.schemas.events_api import Facet, FacetsRequest, FacetsResponse, ValueCount
from app.search.fields import FieldType

FACET_VALUES = 10
INVALID_FIELD = "invalid_facet_field"
NOT_AGGREGATABLE = frozenset({FieldType.TEXT, FieldType.OBJECT_DISABLED, FieldType.FLAT_OBJECT})
AGGREGATABLE = frozenset(FieldType) - NOT_AGGREGATABLE


def build_facets_body(request: FacetsRequest) -> dict[str, Any]:
    aggregations: dict[str, Any] = {}
    for position, name in enumerate(request.fields):
        path = _facet_path(name)
        aggregations[f"values_{position}"] = {"terms": {"field": path, "size": FACET_VALUES}}
        aggregations[f"present_{position}"] = {"filter": {"exists": {"field": path}}}
    return {
        "query": filter_query(request),
        "size": 0,
        "track_total_hits": False,
        "timeout": SEARCH_TIMEOUT,
        "aggs": aggregations,
    }


def _facet_path(name: str) -> str:
    resolved = resolve_for_aggregation(name, AGGREGATABLE, INVALID_FIELD)
    if len(resolved.targets) > 1:
        members = " or ".join(target.path for target in resolved.targets)
        raise ApiError(422, INVALID_FIELD, f"{name} stands for several fields; use {members}")
    return resolved.targets[0].path


def read_facets_response(fields: list[str], response: Mapping[str, Any]) -> FacetsResponse:
    aggregations: Mapping[str, Any] = response.get("aggregations", {})
    return FacetsResponse(
        facets=[
            Facet(
                field=name,
                values=bucket_counts(aggregations.get(f"values_{position}", {})),
                total=aggregations.get(f"present_{position}", {}).get("doc_count", 0),
            )
            for position, name in enumerate(fields)
        ]
    )


def bucket_counts(aggregation: Mapping[str, Any]) -> list[ValueCount]:
    """The buckets of a terms aggregation; a boolean or date key is read as its text."""
    return [
        ValueCount(value=str(bucket.get("key_as_string", bucket["key"])), count=bucket["doc_count"])
        for bucket in aggregation.get("buckets", [])
    ]
