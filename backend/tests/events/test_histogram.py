from datetime import UTC, datetime
from typing import Any

import pytest

from app.db.models.analysis import Severity
from app.events.histogram import (
    AUTO_BUCKETS,
    MAX_BUCKETS,
    MAX_DETECTIONS,
    Extent,
    bucket_count,
    detections_body,
    extent_body,
    histogram_body,
    plan_histogram,
    read_detections,
    read_extent,
    read_histogram,
)
from app.schemas.events_api import (
    HistogramBucket,
    HistogramDetection,
    HistogramRequest,
    TimeRange,
)

SECOND = 1000
MINUTE = 60 * SECOND
HOUR = 60 * MINUTE
T0 = 1_791_892_361_383


def moment(milliseconds: int) -> datetime:
    return datetime.fromtimestamp(milliseconds / 1000, tz=UTC)


def interval_for(span_ms: int, start: int = T0, requested: Any = "auto") -> int:
    request = HistogramRequest(interval=requested)
    return plan_histogram(request, Extent(start, start + span_ms)).interval_ms


def test_a_bucket_count_is_the_number_of_aligned_intervals_the_range_touches() -> None:
    assert bucket_count(0, 0, 10) == 1
    assert bucket_count(0, 9, 10) == 1
    assert bucket_count(9, 10, 10) == 2
    assert bucket_count(5, 25, 10) == 3


@pytest.mark.parametrize(
    ("span_ms", "expected"),
    [
        (0, 1),
        (50, 1),
        (54_999, 500),
        (60 * SECOND, 1000),
        (10 * MINUTE, 10 * SECOND),
        (3 * HOUR, 2 * MINUTE),
    ],
)
def test_auto_picks_the_smallest_nice_step_that_makes_at_most_120_buckets(
    span_ms: int, expected: int
) -> None:
    assert interval_for(span_ms, start=0) == expected


@pytest.mark.parametrize("span_ms", [1, 99, 1_000, 54_999, 999_999, 86_400_000, 40_000_000_000])
@pytest.mark.parametrize("offset", [0, 1, 777])
def test_auto_never_makes_more_than_the_target_number_of_buckets(span_ms: int, offset: int) -> None:
    start = T0 + offset
    chosen = interval_for(span_ms, start=start)

    assert bucket_count(start, start + span_ms, chosen) <= AUTO_BUCKETS


def test_auto_uses_a_second_for_an_empty_range() -> None:
    plan = plan_histogram(HistogramRequest(), Extent(None, None))

    assert (plan.interval_ms, plan.start_ms, plan.end_ms) == (1000, None, None)


def test_an_explicit_interval_is_kept_when_it_makes_few_buckets() -> None:
    assert interval_for(10 * MINUTE, requested=3 * SECOND) == 3 * SECOND


def test_an_explicit_interval_is_widened_until_there_are_at_most_2000_buckets() -> None:
    span = 10 * HOUR
    chosen = interval_for(span, start=0, requested=1)

    assert chosen > 1
    assert bucket_count(0, span, chosen) <= MAX_BUCKETS
    assert bucket_count(0, span, chosen // 2) > MAX_BUCKETS


def test_an_explicit_interval_of_zero_is_refused_by_the_request() -> None:
    with pytest.raises(ValueError, match="greater than or equal to 1"):
        HistogramRequest(interval=0)


def test_a_time_range_decides_the_span_even_where_it_has_no_events() -> None:
    request = HistogramRequest(
        time_range=TimeRange(from_=moment(T0 - MINUTE), to=moment(T0 + 2 * MINUTE))
    )

    plan = plan_histogram(request, Extent(T0, T0 + SECOND))

    assert (plan.start_ms, plan.end_ms) == (T0 - MINUTE, T0 + 2 * MINUTE)


def test_a_time_range_with_one_end_takes_the_other_from_the_events() -> None:
    request = HistogramRequest(time_range=TimeRange(from_=moment(T0 - MINUTE)))

    plan = plan_histogram(request, Extent(T0, T0 + SECOND))

    assert (plan.start_ms, plan.end_ms) == (T0 - MINUTE, T0 + SECOND)


def test_an_empty_range_has_no_buckets() -> None:
    request = HistogramRequest(time_range=TimeRange(from_=moment(T0 + MINUTE), to=moment(T0)))

    assert not plan_histogram(request, Extent(None, None)).bucket_keys()
    assert not plan_histogram(request, Extent(T0, T0)).bucket_keys()


def test_the_extent_is_read_from_the_min_and_max_aggregations() -> None:
    response = {"aggregations": {"first": {"value": 1000.0}, "last": {"value": 5000.0}}}

    assert read_extent(response) == Extent(1000, 5000)


def test_no_events_have_no_extent() -> None:
    assert read_extent(
        {"aggregations": {"first": {"value": None}, "last": {"value": None}}}
    ) == Extent(None, None)
    assert read_extent({"aggregations": {}}) == Extent(None, None)


def test_the_extent_search_runs_on_the_filter_and_fetches_no_hits() -> None:
    body = extent_body(HistogramRequest(query="lane:file"))

    assert body["size"] == 0
    assert body["query"] == {"bool": {"filter": [{"term": {"tartarus.lane": "file"}}]}}
    assert body["aggs"] == {
        "first": {"min": {"field": "@timestamp"}},
        "last": {"max": {"field": "@timestamp"}},
    }


def test_the_histogram_body_buckets_by_the_interval_and_splits_each_by_lane() -> None:
    request = HistogramRequest()
    plan = plan_histogram(request, Extent(0, 55 * SECOND))

    body = histogram_body(request, plan)

    assert body["size"] == 0
    assert body["track_total_hits"] is True
    assert body["aggs"]["over_time"]["date_histogram"] == {
        "field": "@timestamp",
        "fixed_interval": "500ms",
        "min_doc_count": 1,
    }
    assert body["aggs"]["over_time"]["aggs"]["lanes"]["terms"]["field"] == "tartarus.lane"


def histogram_response(*buckets: tuple[int, dict[str, int]], total: int) -> dict[str, Any]:
    return {
        "hits": {"total": {"value": total}},
        "aggregations": {
            "over_time": {
                "buckets": [
                    {
                        "key": key,
                        "doc_count": sum(lanes.values()),
                        "lanes": {
                            "buckets": [{"key": lane, "doc_count": n} for lane, n in lanes.items()]
                        },
                    }
                    for key, lanes in buckets
                ]
            }
        },
    }


def test_the_buckets_are_contiguous_and_the_empty_ones_are_filled_in() -> None:
    plan = plan_histogram(HistogramRequest(interval=1000), Extent(500, 3500))
    response = histogram_response((0, {"api": 2, "file": 1}), (3000, {"api": 4}), total=7)

    histogram = read_histogram(plan, response, [])

    assert histogram.interval_ms == 1000
    assert (histogram.from_, histogram.to) == (moment(500), moment(3500))
    assert histogram.total == 7
    assert histogram.buckets == [
        HistogramBucket(time=moment(0), total=3, by_lane={"api": 2, "file": 1}),
        HistogramBucket(time=moment(1000), total=0, by_lane={}),
        HistogramBucket(time=moment(2000), total=0, by_lane={}),
        HistogramBucket(time=moment(3000), total=4, by_lane={"api": 4}),
    ]


def test_no_events_and_no_range_is_an_empty_histogram() -> None:
    plan = plan_histogram(HistogramRequest(), Extent(None, None))

    histogram = read_histogram(plan, {"hits": {"total": {"value": 0}}, "aggregations": {}}, [])

    assert (histogram.from_, histogram.to, histogram.buckets, histogram.total) == (
        None,
        None,
        [],
        0,
    )


def test_the_detection_search_keeps_the_filter_and_only_alerts_in_time_order() -> None:
    body = detections_body(HistogramRequest(query="lane:file"))

    assert body["query"] == {
        "bool": {
            "filter": [
                {"bool": {"filter": [{"term": {"tartarus.lane": "file"}}]}},
                {"term": {"event.kind": "alert"}},
            ]
        }
    }
    assert body["size"] == MAX_DETECTIONS == 500
    assert body["sort"] == [{"@timestamp": "asc"}, {"event.sequence": "asc"}, {"event.id": "asc"}]


def test_detections_are_read_with_their_rule_and_severity() -> None:
    response = {
        "hits": {
            "hits": [
                {
                    "_source": {
                        "@timestamp": "2026-10-13T12:12:41.398Z",
                        "event": {"id": "a1", "severity": 3},
                        "rule": {"name": "creates_exe", "ruleset": "cape"},
                    }
                }
            ]
        }
    }

    assert read_detections(response) == [
        HistogramDetection(
            time=datetime(2026, 10, 13, 12, 12, 41, 398_000, tzinfo=UTC),
            id="a1",
            name="creates_exe",
            severity=Severity.HIGH,
            ruleset="cape",
        )
    ]
