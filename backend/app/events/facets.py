"""The body of `POST events/facets` and the facets its response becomes."""

from collections.abc import Mapping
from typing import Any

from app.events.aggregatable import resolve_single_field
from app.events.execution import SEARCH_TIMEOUT
from app.events.filters import CompiledChip, chips_query, compile_filter
from app.schemas.events_api import Facet, FacetsRequest, FacetsResponse, ValueCount
from app.search.fields import FieldType

FACET_VALUES = 10
INVALID_FIELD = "invalid_facet_field"
FACET = "facet_"
VALUES = "values"
PRESENT = "present"
NOT_AGGREGATABLE = frozenset({FieldType.TEXT, FieldType.OBJECT_DISABLED, FieldType.FLAT_OBJECT})
AGGREGATABLE = frozenset(FieldType) - NOT_AGGREGATABLE


def build_facets_body(request: FacetsRequest) -> dict[str, Any]:
    """Each facet counts under the filter without the chips on its own field, so the analyst
    can still see and pick the other values of a field they have already narrowed.

    The request's query keeps what every facet shares, which includes chips on fields that are
    not facets; each facet is a `filter` aggregation holding only the chips on the other facets.
    """
    paths = [_facet_path(name) for name in request.fields]
    compiled = compile_filter(request)
    facet_paths = set(paths)
    on_facets = [chip for chip in compiled.chips if chip.paths & facet_paths]
    elsewhere = [chip for chip in compiled.chips if not chip.paths & facet_paths]
    return {
        "query": compiled.query_with(elsewhere),
        "size": 0,
        "track_total_hits": False,
        "timeout": SEARCH_TIMEOUT,
        "aggs": {
            f"{FACET}{position}": _facet_aggregation(
                path, [chip for chip in on_facets if path not in chip.paths]
            )
            for position, path in enumerate(paths)
        },
    }


def _facet_aggregation(path: str, chips: list[CompiledChip]) -> dict[str, Any]:
    return {
        "filter": chips_query(chips),
        "aggs": {
            VALUES: {"terms": {"field": path, "size": FACET_VALUES}},
            PRESENT: {"filter": {"exists": {"field": path}}},
        },
    }


def _facet_path(name: str) -> str:
    return resolve_single_field(name, AGGREGATABLE, INVALID_FIELD).path


def read_facets_response(fields: list[str], response: Mapping[str, Any]) -> FacetsResponse:
    aggregations: Mapping[str, Any] = response.get("aggregations", {})
    facets = [aggregations.get(f"{FACET}{position}", {}) for position in range(len(fields))]
    return FacetsResponse(
        facets=[
            Facet(
                field=name,
                values=bucket_counts(facet.get(VALUES, {})),
                total=facet.get(PRESENT, {}).get("doc_count", 0),
            )
            for name, facet in zip(fields, facets, strict=True)
        ]
    )


def bucket_counts(aggregation: Mapping[str, Any]) -> list[ValueCount]:
    """The buckets of a terms aggregation; a boolean or date key is read as its text."""
    return [
        ValueCount(value=str(bucket.get("key_as_string", bucket["key"])), count=bucket["doc_count"])
        for bucket in aggregation.get("buckets", [])
    ]
