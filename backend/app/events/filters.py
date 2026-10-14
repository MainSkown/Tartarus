"""The filter body of every events endpoint as one OpenSearch query."""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from app.errors import ApiError
from app.query.clauses import lowercase_like_index
from app.query.compiler import compile_filter_chip, compile_query
from app.query.errors import QueryError
from app.query.field_resolution import resolve_query_field
from app.schemas.events_api import EventFilter, TimeRange

Query = dict[str, Any]

EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
ONE_MILLISECOND = timedelta(milliseconds=1)
MATCH_ALL: Query = {"match_all": {}}


@dataclass(frozen=True, slots=True)
class CompiledChip:
    query: Query
    negate: bool
    paths: frozenset[str]


@dataclass(frozen=True, slots=True)
class CompiledFilter:
    """The filter compiled once, with its chips kept apart so a facet can leave some out.

    `common` is what always applies: the query text, the time range, the lanes and the pids.
    """

    common: list[Query]
    chips: tuple[CompiledChip, ...]

    def query_with(self, chips: Iterable[CompiledChip]) -> Query:
        return _anded(self.common, chips)


def compile_filter(event_filter: EventFilter) -> CompiledFilter:
    """Compiles the query and every chip.

    A query or chip that does not compile raises a 422 carrying every error with its span.
    """
    errors: list[dict[str, Any]] = []
    common: list[Query] = []
    chips: list[CompiledChip] = []

    query = compile_query(event_filter.query)
    errors.extend(_described(error, None) for error in query.errors)
    if query.query is not None:
        common.append(query.query)

    for index, chip in enumerate(event_filter.filters):
        compiled = compile_filter_chip(chip.field, chip.value)
        errors.extend(_described(error, index) for error in compiled.errors)
        if compiled.query is not None:
            chips.append(CompiledChip(compiled.query, chip.negate, _paths_of(chip.field)))

    if errors:
        raise ApiError(422, "invalid_query", "The query does not compile", {"errors": errors})

    common.extend(_restrictions(event_filter))
    return CompiledFilter(common, tuple(chips))


def filter_query(event_filter: EventFilter) -> Query:
    """The query ANDed with every chip, time range, lane list and pid list."""
    compiled = compile_filter(event_filter)
    return compiled.query_with(compiled.chips)


def chips_query(chips: Iterable[CompiledChip]) -> Query:
    """Only the chips ANDed, negated ones excluded; match-all for none."""
    return _anded([], chips)


def _anded(required: list[Query], chips: Iterable[CompiledChip]) -> Query:
    required = list(required)
    excluded: list[Query] = []
    for chip in chips:
        (excluded if chip.negate else required).append(chip.query)
    return _bool_of(required, excluded)


def _paths_of(field: str) -> frozenset[str]:
    resolved = resolve_query_field(field)
    return frozenset() if resolved is None else frozenset(t.path for t in resolved.targets)


def _described(error: QueryError, filter_index: int | None) -> dict[str, Any]:
    return {
        "start": error.start,
        "end": error.end,
        "message": error.message,
        "suggestion": error.suggestion,
        "filter_index": filter_index,
    }


def _restrictions(event_filter: EventFilter) -> list[Query]:
    restrictions: list[Query] = []
    if event_filter.time_range is not None and (
        range_clause := _time_range(event_filter.time_range)
    ):
        restrictions.append(range_clause)
    if event_filter.lanes is not None:
        restrictions.append(
            {
                "terms": {
                    "tartarus.lane": [lowercase_like_index(lane) for lane in event_filter.lanes]
                }
            }
        )
    if event_filter.pids is not None:
        restrictions.append({"terms": {"process.pid": event_filter.pids}})
    return restrictions


def _time_range(time_range: TimeRange) -> Query | None:
    bounds = {
        bound: epoch_millis(moment)
        for bound, moment in (("gte", time_range.from_), ("lte", time_range.to))
        if moment is not None
    }
    return {"range": {"@timestamp": bounds}} if bounds else None


def epoch_millis(moment: datetime) -> int:
    """Whole milliseconds since the epoch, rounded down; a time without a zone is taken as UTC."""
    aware = moment if moment.tzinfo is not None else moment.replace(tzinfo=UTC)
    return (aware - EPOCH) // ONE_MILLISECOND


def _bool_of(required: list[Query], excluded: list[Query]) -> Query:
    if not required and not excluded:
        return MATCH_ALL
    body: Query = {}
    if required:
        body["filter"] = required
    if excluded:
        body["must_not"] = excluded
    return {"bool": body}
