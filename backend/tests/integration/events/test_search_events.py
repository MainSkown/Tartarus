from datetime import timedelta
from typing import Any

import pytest

from tests.integration.events.conftest import (
    all_events,
    events_url,
    in_time_order,
    moment,
    post_ok,
)
from tests.integration.views.conftest import ViewStack
from tests.integration.views.helpers import (
    add_analysis_without_index,
    index_extra_events,
    synthetic_event,
)

pytestmark = pytest.mark.integration

TOTAL = 703


async def every_page(
    stack: ViewStack, size: int, sort: str, **filters: Any
) -> tuple[list[dict[str, Any]], list[int]]:
    events: list[dict[str, Any]] = []
    totals: list[int] = []
    cursor: str | None = None
    while True:
        body = {"size": size, "sort": sort, "search_after": cursor, **filters}
        page = await post_ok(stack, "search", body)
        events.extend(page["events"])
        totals.append(page["total"])
        cursor = page["next_cursor"]
        if cursor is None:
            return events, totals


@pytest.mark.parametrize("sort", ["@timestamp", "-@timestamp"])
@pytest.mark.parametrize("size", [1, 37, 100, 500])
async def test_paging_reaches_every_event_once_and_in_order(
    view_stack: ViewStack, sort: str, size: int
) -> None:
    descending = sort.startswith("-")

    events, totals = await every_page(view_stack, size, sort)

    expected = [
        event["event"]["id"] for event in in_time_order(await all_events(view_stack), descending)
    ]
    assert [event["id"] for event in events] == expected
    assert len(expected) == TOTAL
    assert set(totals) == {TOTAL}


async def test_a_page_that_ends_exactly_at_the_end_has_no_next_page(view_stack: ViewStack) -> None:
    page = await post_ok(view_stack, "search", {"size": 500, "query": "lane:network"})

    assert (len(page["events"]), page["total"], page["next_cursor"]) == (213, 213, None)


async def test_events_that_tie_on_time_and_sequence_page_by_id_and_events_without_sequence_too(
    view_stack: ViewStack,
) -> None:
    tied = [
        synthetic_event(f"tie-{n}", "2026-10-13T13:00:00.000Z", "tie", "file") for n in range(1, 6)
    ]
    without_sequence = [
        synthetic_event(f"bare-{n}", "2026-10-13T13:00:00.000Z", "bare", "file")
        for n in range(1, 4)
    ]
    for event in tied:
        event["event"]["sequence"] = 7
    for event in without_sequence:
        del event["event"]["sequence"]
    await index_extra_events(view_stack, [*tied, *without_sequence])

    for sort in ("@timestamp", "-@timestamp"):
        events, _ = await every_page(
            view_stack, 1, sort, time_range={"from": "2026-10-13T13:00:00Z"}
        )
        ids = [event["id"] for event in events]
        assert sorted(ids) == sorted(
            ["tie-1", "tie-2", "tie-3", "tie-4", "tie-5", "bare-1", "bare-2", "bare-3"]
        )
        assert len(set(ids)) == 8


async def test_the_query_and_the_chips_are_anded(view_stack: ViewStack) -> None:
    body = {
        "query": "lane:api",
        "filters": [{"field": "process.name", "value": "benign.exe"}],
        "size": 500,
    }

    page = await post_ok(view_stack, "search", body)

    expected = [
        event
        for event in await all_events(view_stack)
        if event["tartarus"]["lane"] == "api"
        and event.get("process", {}).get("name", "").lower() == "benign.exe"
    ]
    assert page["total"] == len(expected) > 0
    assert {event["id"] for event in page["events"]} == {e["event"]["id"] for e in expected}


async def test_a_negated_chip_excludes_what_it_names(view_stack: ViewStack) -> None:
    body = {
        "query": "lane:api",
        "filters": [{"field": "api", "value": "NtOpenKey", "negate": True}],
        "size": 1,
    }

    page = await post_ok(view_stack, "search", body)

    expected = [
        event
        for event in await all_events(view_stack)
        if event["tartarus"]["lane"] == "api" and event["api"]["name"] != "NtOpenKey"
    ]
    assert page["total"] == len(expected) > 0


async def test_lanes_and_pids_restrict_the_events(view_stack: ViewStack) -> None:
    page = await post_ok(
        view_stack, "search", {"lanes": ["file", "registry"], "pids": [10116, 9632], "size": 500}
    )

    expected = [
        event
        for event in await all_events(view_stack)
        if event["tartarus"]["lane"] in ("file", "registry")
        and event.get("process", {}).get("pid") in (10116, 9632)
    ]
    assert page["total"] == len(expected) > 0
    assert {event["lane"] for event in page["events"]} <= {"file", "registry"}


async def test_the_time_range_includes_both_ends(view_stack: ViewStack) -> None:
    ordered = in_time_order(await all_events(view_stack))
    first, last = moment(ordered[100]), moment(ordered[300])

    page = await post_ok(
        view_stack,
        "search",
        {"time_range": {"from": first.isoformat(), "to": last.isoformat()}, "size": 500},
    )

    expected = [event for event in await all_events(view_stack) if first <= moment(event) <= last]
    assert page["total"] == len(expected)
    assert page["events"][0]["time"].startswith(first.strftime("%Y-%m-%dT%H:%M:%S"))


async def test_a_time_range_before_everything_finds_nothing(view_stack: ViewStack) -> None:
    earliest = moment(in_time_order(await all_events(view_stack))[0])

    page = await post_ok(
        view_stack,
        "search",
        {"time_range": {"to": (earliest - timedelta(milliseconds=1)).isoformat()}},
    )

    assert (page["events"], page["total"], page["next_cursor"]) == ([], 0, None)


async def test_an_event_carries_the_typed_fields_the_table_needs(view_stack: ViewStack) -> None:
    page = await post_ok(view_stack, "search", {"query": "kind:alert", "size": 500})

    alert = next(event for event in page["events"] if event["rule_name"] is not None)
    source = next(e for e in await all_events(view_stack) if e["event"]["id"] == alert["id"])
    assert alert["kind"] == "alert"
    assert alert["rule_name"] == source["rule"]["name"]
    assert alert["lane"] == source["tartarus"]["lane"]
    assert alert["summary"] == source["tartarus"]["summary"]
    assert alert["time"].startswith(source["@timestamp"][:19])
    assert alert["severity"] in {"info", "low", "medium", "high", "critical"}


async def test_a_query_that_does_not_compile_is_a_422_with_its_spans(
    view_stack: ViewStack,
) -> None:
    response = await view_stack.client.post(
        events_url(view_stack, "search"), json={"query": "procss.name:x"}
    )

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "invalid_query"
    assert error["details"]["errors"] == [
        {
            "start": 0,
            "end": 11,
            "message": "unknown field 'procss.name'; did you mean 'process.name'?",
            "suggestion": "process.name",
            "filter_index": None,
        }
    ]


async def test_a_bad_chip_is_a_422_naming_the_chip(view_stack: ViewStack) -> None:
    response = await view_stack.client.post(
        events_url(view_stack, "search"),
        json={"filters": [{"field": "process.pid", "value": "abc"}]},
    )

    assert response.status_code == 422
    (error,) = response.json()["error"]["details"]["errors"]
    assert (error["start"], error["end"], error["filter_index"]) == (12, 15, 0)


async def test_a_malformed_cursor_is_a_422(view_stack: ViewStack) -> None:
    response = await view_stack.client.post(
        events_url(view_stack, "search"), json={"search_after": "junk"}
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_cursor"


@pytest.mark.parametrize("size", [0, 501])
async def test_a_page_size_out_of_range_is_a_422(view_stack: ViewStack, size: int) -> None:
    response = await view_stack.client.post(events_url(view_stack, "search"), json={"size": size})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


async def test_an_unknown_analysis_is_a_404_in_the_error_envelope(view_stack: ViewStack) -> None:
    response = await view_stack.client.post(
        events_url(view_stack, "search", analysis_id=999_999), json={}
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


async def test_an_analysis_with_no_index_has_no_events(view_stack: ViewStack) -> None:
    bare = await add_analysis_without_index(view_stack)

    response = await view_stack.client.post(
        events_url(view_stack, "search", analysis_id=bare), json={}
    )

    assert response.status_code == 200
    assert response.json() == {"events": [], "total": 0, "next_cursor": None}
