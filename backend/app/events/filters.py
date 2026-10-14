"""The filter body of every events endpoint as one OpenSearch query."""

from datetime import UTC, datetime, timedelta
from typing import Any

from app.errors import ApiError
from app.query.clauses import lowercase_like_index
from app.query.compiler import compile_filter_chip, compile_query
from app.query.errors import QueryError
from app.schemas.events_api import EventFilter, TimeRange

Query = dict[str, Any]

EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
ONE_MILLISECOND = timedelta(milliseconds=1)
MATCH_ALL: Query = {"match_all": {}}


def filter_query(event_filter: EventFilter) -> Query:
    """The query ANDed with every chip, time range, lane list and pid list.

    A query or chip that does not compile raises a 422 carrying every error with its span.
    """
    errors: list[dict[str, Any]] = []
    required: list[Query] = []
    excluded: list[Query] = []

    query = compile_query(event_filter.query)
    errors.extend(_described(error, None) for error in query.errors)
    if query.query is not None:
        required.append(query.query)

    for index, chip in enumerate(event_filter.filters):
        compiled = compile_filter_chip(chip.field, chip.value)
        errors.extend(_described(error, index) for error in compiled.errors)
        if compiled.query is not None:
            (excluded if chip.negate else required).append(compiled.query)

    if errors:
        raise ApiError(422, "invalid_query", "The query does not compile", {"errors": errors})

    required.extend(_restrictions(event_filter))
    return _bool_of(required, excluded)


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
