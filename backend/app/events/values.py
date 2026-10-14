"""The search behind value autocomplete: top values of a keyword field by prefix."""

from collections import Counter
from collections.abc import Mapping
from typing import Any

from app.events.aggregatable import resolve_for_aggregation
from app.events.execution import SEARCH_TIMEOUT
from app.events.facets import bucket_counts
from app.events.filters import MATCH_ALL
from app.query.clauses import lowercase_like_index
from app.schemas.events_api import FieldValues, ValueCount
from app.search.fields import FieldType

INVALID_FIELD = "invalid_value_field"
KEYWORD_TYPES = frozenset({FieldType.KEYWORD, FieldType.KEYWORD_WITH_TEXT})
LUCENE_REGEX_OPERATORS = frozenset('.?+*|{}[]()"\\#@&<>~')


def value_paths(field: str) -> list[str]:
    """The index fields a name or alias stands for; a composite alias gives all its members."""
    resolved = resolve_for_aggregation(field, KEYWORD_TYPES, INVALID_FIELD)
    return [target.path for target in resolved.targets]


def include_pattern(prefix: str) -> str | None:
    """A regex for the indexed terms, which are lowercase, so the match is case-insensitive."""
    if not prefix:
        return None
    escaped = "".join(
        f"\\{character}" if character in LUCENE_REGEX_OPERATORS else character
        for character in lowercase_like_index(prefix)
    )
    return f"{escaped}.*"


def build_values_body(paths: list[str], prefix: str, limit: int) -> dict[str, Any]:
    include = include_pattern(prefix)
    aggregations = {
        f"values_{position}": {"terms": _terms(path, limit, include)}
        for position, path in enumerate(paths)
    }
    return {
        "query": MATCH_ALL,
        "size": 0,
        "track_total_hits": False,
        "timeout": SEARCH_TIMEOUT,
        "aggs": aggregations,
    }


def _terms(path: str, limit: int, include: str | None) -> dict[str, Any]:
    terms: dict[str, Any] = {"field": path, "size": limit}
    if include is not None:
        terms["include"] = include
    return terms


def read_values(limit: int, response: Mapping[str, Any]) -> FieldValues:
    """Merges the fields' values, summing the counts of a value that several have."""
    totals: Counter[str] = Counter()
    for name, aggregation in response.get("aggregations", {}).items():
        if name.startswith("values_"):
            for value in bucket_counts(aggregation):
                totals[value.value] += value.count
    ranked = sorted(totals.items(), key=lambda item: (-item[1], item[0]))[:limit]
    return FieldValues(values=[ValueCount(value=value, count=count) for value, count in ranked])
