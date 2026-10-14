from datetime import UTC, datetime
from typing import Any

import pytest

from app.errors import ApiError
from app.events.filters import filter_query
from app.query.compiler import compile_query
from app.schemas.events_api import EventFilter, FilterChip, TimeRange
from app.search.fields import Lane


def query_clause(text: str) -> dict[str, Any]:
    compiled = compile_query(text)
    assert compiled.query is not None
    return compiled.query


def chip(field: str, value: str, negate: bool = False) -> FilterChip:
    return FilterChip(field=field, value=value, negate=negate)


def test_no_filter_matches_everything() -> None:
    assert filter_query(EventFilter()) == {"match_all": {}}


def test_a_query_alone_is_the_one_filter() -> None:
    assert filter_query(EventFilter(query="lane:file")) == {
        "bool": {"filter": [query_clause("lane:file")]}
    }


def test_chips_are_anded_with_the_query_and_negated_chips_are_excluded() -> None:
    result = filter_query(
        EventFilter(
            query="lane:file",
            filters=[chip("process.name", "cmd.exe"), chip("action", "file-written", negate=True)],
        )
    )

    assert result == {
        "bool": {
            "filter": [query_clause("lane:file"), query_clause("process.name:cmd.exe")],
            "must_not": [query_clause("action:file-written")],
        }
    }


def test_time_range_lanes_and_pids_are_further_filters() -> None:
    result = filter_query(
        EventFilter(
            time_range=TimeRange(
                from_=datetime(2026, 10, 13, 12, 0, 0, 500_000, tzinfo=UTC),
                to=datetime(2026, 10, 13, 12, 1, tzinfo=UTC),
            ),
            lanes=[Lane.FILE, Lane.NETWORK],
            pids=[10, 20],
        )
    )

    assert result == {
        "bool": {
            "filter": [
                {"range": {"@timestamp": {"gte": 1791892800500, "lte": 1791892860000}}},
                {"terms": {"tartarus.lane": ["file", "network"]}},
                {"terms": {"process.pid": [10, 20]}},
            ]
        }
    }


def test_a_time_range_with_one_end_leaves_the_other_open() -> None:
    result = filter_query(
        EventFilter(time_range=TimeRange(to=datetime(2026, 10, 13, 12, 1, tzinfo=UTC)))
    )

    assert result == {"bool": {"filter": [{"range": {"@timestamp": {"lte": 1791892860000}}}]}}


def test_a_time_range_with_no_end_is_no_filter() -> None:
    assert filter_query(EventFilter(time_range=TimeRange())) == {"match_all": {}}


def test_a_time_without_a_zone_is_utc() -> None:
    naive = EventFilter(time_range=TimeRange(from_=datetime(2026, 10, 13, 12, 0)))

    assert filter_query(naive) == {
        "bool": {"filter": [{"range": {"@timestamp": {"gte": 1791892800000}}}]}
    }


def test_an_empty_lane_or_pid_list_matches_nothing() -> None:
    result = filter_query(EventFilter(lanes=[], pids=[]))

    assert result == {
        "bool": {"filter": [{"terms": {"tartarus.lane": []}}, {"terms": {"process.pid": []}}]}
    }


def rejected(filters: EventFilter) -> dict[str, Any]:
    with pytest.raises(ApiError) as caught:
        filter_query(filters)
    assert caught.value.status_code == 422
    assert caught.value.code == "invalid_query"
    return caught.value.details


def test_a_bad_query_is_refused_with_the_error_spans() -> None:
    details = rejected(EventFilter(query="procss.name:x"))

    assert details == {
        "errors": [
            {
                "start": 0,
                "end": 11,
                "message": "unknown field 'procss.name'; did you mean 'process.name'?",
                "suggestion": "process.name",
                "filter_index": None,
            }
        ]
    }


def test_a_bad_chip_is_refused_and_says_which_chip_it_was() -> None:
    details = rejected(
        EventFilter(filters=[chip("process.name", "cmd.exe"), chip("process.pid", "abc")])
    )

    assert details["errors"] == [
        {
            "start": 12,
            "end": 15,
            "message": "'abc' is not a whole number",
            "suggestion": None,
            "filter_index": 1,
        }
    ]


def test_the_errors_of_the_query_and_of_every_chip_come_together() -> None:
    details = rejected(
        EventFilter(query="lane:(", filters=[chip("nope", "x"), chip("process.pid", "abc")])
    )

    assert [error["filter_index"] for error in details["errors"]] == [None, 0, 1]
