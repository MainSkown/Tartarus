from collections import Counter
from datetime import datetime, timedelta
from itertools import pairwise
from typing import Any

import pytest

from tests.integration.events.conftest import all_events, events_url, in_time_order, moment, post_ok
from tests.integration.views.conftest import ViewStack
from tests.integration.views.helpers import add_analysis_without_index

pytestmark = pytest.mark.integration

AUTO_BUCKETS = 120


def when(text: str) -> datetime:
    return datetime.fromisoformat(text)


def lane_totals(histogram: dict[str, Any]) -> Counter[str]:
    totals: Counter[str] = Counter()
    for bucket in histogram["buckets"]:
        totals.update(bucket["by_lane"])
    return totals


def assert_adds_up(histogram: dict[str, Any], expected_total: int) -> None:
    assert histogram["total"] == expected_total
    assert sum(bucket["total"] for bucket in histogram["buckets"]) == expected_total
    for bucket in histogram["buckets"]:
        assert sum(bucket["by_lane"].values()) == bucket["total"]


async def test_the_histogram_sums_to_the_total_and_to_each_lane(view_stack: ViewStack) -> None:
    histogram = await post_ok(view_stack, "histogram", {})

    events = await all_events(view_stack)
    assert_adds_up(histogram, len(events))
    assert lane_totals(histogram) == Counter(event["tartarus"]["lane"] for event in events)


async def test_each_lane_total_equals_a_search_on_that_lane(view_stack: ViewStack) -> None:
    histogram = await post_ok(view_stack, "histogram", {"interval": 1000})

    for lane, count in lane_totals(histogram).items():
        page = await post_ok(view_stack, "search", {"lanes": [lane], "size": 1})
        assert page["total"] == count


async def test_auto_makes_contiguous_buckets_that_hold_the_first_and_last_event(
    view_stack: ViewStack,
) -> None:
    histogram = await post_ok(view_stack, "histogram", {})

    ordered = in_time_order(await all_events(view_stack))
    first, last = moment(ordered[0]), moment(ordered[-1])
    interval = histogram["interval_ms"]
    buckets = histogram["buckets"]
    assert interval == 500
    assert 0 < len(buckets) <= AUTO_BUCKETS
    assert when(histogram["from"]) == first
    assert when(histogram["to"]) == last
    width = timedelta(milliseconds=interval)
    starts = [when(bucket["time"]) for bucket in buckets]
    assert all(later - earlier == width for earlier, later in pairwise(starts))
    assert starts[0] <= first < starts[0] + width
    assert starts[-1] <= last < starts[-1] + width
    assert buckets[0]["total"] > 0
    assert buckets[-1]["total"] > 0


async def test_empty_stretches_between_events_are_buckets_with_zero(view_stack: ViewStack) -> None:
    histogram = await post_ok(view_stack, "histogram", {"interval": 1})

    assert histogram["interval_ms"] > 1
    assert any(bucket["total"] == 0 and bucket["by_lane"] == {} for bucket in histogram["buckets"])
    assert len(histogram["buckets"]) <= 2000


async def test_an_explicit_interval_is_used_when_it_is_coarse_enough(view_stack: ViewStack) -> None:
    histogram = await post_ok(view_stack, "histogram", {"interval": 10_000})

    assert histogram["interval_ms"] == 10_000
    assert len(histogram["buckets"]) <= 7
    assert_adds_up(histogram, 703)


async def test_the_histogram_follows_the_filter(view_stack: ViewStack) -> None:
    histogram = await post_ok(view_stack, "histogram", {"query": "lane:network"})

    assert_adds_up(histogram, 213)
    assert set(lane_totals(histogram)) == {"network"}


async def test_a_time_range_wider_than_the_data_is_filled_with_empty_buckets(
    view_stack: ViewStack,
) -> None:
    ordered = in_time_order(await all_events(view_stack))
    first = moment(ordered[0])
    time_range = {"from": "2026-10-13T12:11:00Z", "to": "2026-10-13T12:15:00Z"}

    histogram = await post_ok(view_stack, "histogram", {"time_range": time_range})

    assert when(histogram["from"]) == when("2026-10-13T12:11:00Z")
    assert when(histogram["to"]) == when("2026-10-13T12:15:00Z")
    assert histogram["buckets"][0]["total"] == 0
    assert histogram["buckets"][-1]["total"] == 0
    assert_adds_up(histogram, 703)
    assert first > when(histogram["from"])


async def test_a_narrow_time_range_counts_only_its_events(view_stack: ViewStack) -> None:
    ordered = in_time_order(await all_events(view_stack))
    start, end = moment(ordered[100]), moment(ordered[300])
    expected = [event for event in ordered if start <= moment(event) <= end]

    histogram = await post_ok(
        view_stack, "histogram", {"time_range": {"from": start.isoformat(), "to": end.isoformat()}}
    )

    assert_adds_up(histogram, len(expected))


async def test_the_detections_are_the_alerts_in_time_order(view_stack: ViewStack) -> None:
    histogram = await post_ok(view_stack, "histogram", {})

    alerts = in_time_order(
        [event for event in await all_events(view_stack) if event["event"]["kind"] == "alert"]
    )
    assert len(alerts) == 12
    assert [detection["id"] for detection in histogram["detections"]] == [
        alert["event"]["id"] for alert in alerts
    ]
    first = histogram["detections"][0]
    assert first["name"] == alerts[0]["rule"]["name"]
    assert first["ruleset"] == alerts[0]["rule"]["ruleset"]
    assert first["severity"] in {"info", "low", "medium", "high", "critical"}
    assert when(first["time"]) == moment(alerts[0])


async def test_detections_are_only_those_the_filter_keeps(view_stack: ViewStack) -> None:
    histogram = await post_ok(view_stack, "histogram", {"query": "NOT kind:alert"})

    assert histogram["detections"] == []
    assert_adds_up(histogram, 691)


async def test_an_analysis_with_no_index_has_an_empty_histogram(view_stack: ViewStack) -> None:
    bare = await add_analysis_without_index(view_stack)

    response = await view_stack.client.post(
        events_url(view_stack, "histogram", analysis_id=bare), json={}
    )

    assert response.status_code == 200
    assert response.json() == {
        "interval_ms": 1000,
        "from": None,
        "to": None,
        "total": 0,
        "buckets": [],
        "detections": [],
    }


async def test_a_filter_that_matches_nothing_has_an_empty_histogram(view_stack: ViewStack) -> None:
    histogram = await post_ok(view_stack, "histogram", {"query": "process.name:nothing.exe"})

    assert (histogram["from"], histogram["to"], histogram["buckets"], histogram["total"]) == (
        None,
        None,
        [],
        0,
    )


async def test_a_query_that_does_not_compile_is_a_422(view_stack: ViewStack) -> None:
    response = await view_stack.client.post(
        events_url(view_stack, "histogram"), json={"query": "nope:x"}
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_query"


@pytest.mark.parametrize("interval", [0, -5, "weekly"])
async def test_a_bad_interval_is_a_422(view_stack: ViewStack, interval: Any) -> None:
    response = await view_stack.client.post(
        events_url(view_stack, "histogram"), json={"interval": interval}
    )

    assert response.status_code == 422


async def test_an_unknown_analysis_is_a_404(view_stack: ViewStack) -> None:
    response = await view_stack.client.post(
        events_url(view_stack, "histogram", analysis_id=999_999), json={}
    )

    assert response.status_code == 404
