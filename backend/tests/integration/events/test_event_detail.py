from typing import Any
from urllib.parse import quote

import pytest

from tests.integration.events.conftest import all_events, in_time_order
from tests.integration.views.conftest import ViewStack
from tests.integration.views.helpers import (
    add_analysis_without_index,
    index_extra_events,
    synthetic_event,
)

pytestmark = pytest.mark.integration

STRANGE_ID = "processes/12:34 a?b#c%d-1"
SHOUTED_ID = "Procs/ABC:1-2"


async def get_event(stack: ViewStack, event_id: str, analysis_id: int | None = None) -> Any:
    target = stack.analysis_id if analysis_id is None else analysis_id
    return await stack.client.get(f"/api/analyses/{target}/events/{quote(event_id, safe='')}")


async def detail_ok(stack: ViewStack, event_id: str) -> Any:
    response = await get_event(stack, event_id)
    assert response.status_code == 200, response.text
    return response.json()


def alert_naming(event_id: str, number: int, *named: str, timestamp: str) -> dict[str, Any]:
    alert = synthetic_event(f"alert-{event_id}-{number}", timestamp, "signature-matched", "process")
    alert["event"]["kind"] = "alert"
    alert["related"] = {"events": list(named)}
    return alert


async def test_the_detail_of_an_alert_names_the_events_that_triggered_it(
    view_stack: ViewStack,
) -> None:
    events = await all_events(view_stack)
    by_id = {event["event"]["id"]: event for event in events}
    alert = next(
        event
        for event in events
        if event["event"]["kind"] == "alert" and len(event.get("related", {}).get("events", [])) > 1
    )
    named = [by_id[i] for i in alert["related"]["events"] if i in by_id]

    detail = await detail_ok(view_stack, alert["event"]["id"])

    assert detail["event"]["id"] == alert["event"]["id"]
    assert detail["event"]["kind"] == "alert"
    assert detail["event"]["rule_name"] == alert["rule"]["name"]
    references = detail["related"]["references"]
    assert [item["id"] for item in references["items"]] == [
        event["event"]["id"] for event in in_time_order(named)
    ]
    assert references["total"] == len(named) > 1


async def test_a_triggering_event_lists_the_alerts_that_name_it(view_stack: ViewStack) -> None:
    events = await all_events(view_stack)
    alert = next(
        event for event in events if event["event"]["kind"] == "alert" and event.get("related")
    )
    triggering = alert["related"]["events"][0]
    alerts_naming = [
        event["event"]["id"]
        for event in in_time_order(events)
        if triggering in event.get("related", {}).get("events", [])
    ]

    detail = await detail_ok(view_stack, triggering)

    referenced_by = detail["related"]["referenced_by"]
    assert [item["id"] for item in referenced_by["items"]] == alerts_naming
    assert alert["event"]["id"] in alerts_naming
    assert referenced_by["total"] == len(alerts_naming)


async def test_the_detail_has_the_whole_source_including_the_raw_record(
    view_stack: ViewStack,
) -> None:
    events = await all_events(view_stack)
    api_call = next(event for event in events if event["tartarus"]["lane"] == "api")

    detail = await detail_ok(view_stack, api_call["event"]["id"])

    assert detail["source"] == api_call
    assert detail["source"]["tartarus"]["raw"]
    assert detail["event"]["api_name"] == api_call["api"]["name"]
    assert detail["related"]["references"] == {"items": [], "total": 0}


async def test_a_search_leaves_the_raw_record_out_but_the_detail_has_it(
    view_stack: ViewStack,
) -> None:
    page = await view_stack.client.post(
        f"/api/analyses/{view_stack.analysis_id}/events/search", json={"size": 1}
    )

    assert "raw" not in page.text


async def test_an_id_with_slashes_colons_and_reserved_characters_is_found(
    view_stack: ViewStack,
) -> None:
    strange = synthetic_event(STRANGE_ID, "2026-10-13T13:00:00.000Z", "strange", "file")
    alert = alert_naming("strange", 1, STRANGE_ID, timestamp="2026-10-13T13:00:01.000Z")
    await index_extra_events(view_stack, [strange, alert])

    detail = await detail_ok(view_stack, STRANGE_ID)

    assert detail["event"]["id"] == STRANGE_ID
    assert [item["id"] for item in detail["related"]["referenced_by"]["items"]] == [
        alert["event"]["id"]
    ]


async def test_the_slashes_and_colons_of_an_id_work_unencoded_too(view_stack: ViewStack) -> None:
    event_id = "processes/12:34-1"
    await index_extra_events(
        view_stack, [synthetic_event(event_id, "2026-10-13T13:00:00.000Z", "plain", "file")]
    )

    response = await view_stack.client.get(
        f"/api/analyses/{view_stack.analysis_id}/events/{event_id}"
    )

    assert response.status_code == 200
    assert response.json()["event"]["id"] == event_id


async def test_an_id_with_capitals_finds_the_alerts_that_name_it(view_stack: ViewStack) -> None:
    shouted = synthetic_event(SHOUTED_ID, "2026-10-13T13:00:00.000Z", "shouted", "file")
    alert = alert_naming("shouted", 3, SHOUTED_ID, timestamp="2026-10-13T13:00:01.000Z")
    await index_extra_events(view_stack, [shouted, alert])

    detail = await detail_ok(view_stack, SHOUTED_ID)

    assert detail["event"]["id"] == SHOUTED_ID
    assert detail["related"]["referenced_by"]["total"] == 1
    assert detail["related"]["referenced_by"]["items"][0]["id"] == alert["event"]["id"]


async def test_each_direction_lists_fifty_and_counts_all(view_stack: ViewStack) -> None:
    named = [
        synthetic_event(f"named-{n}", f"2026-10-13T13:00:{n % 60:02d}.000Z", "named", "file")
        for n in range(60)
    ]
    big_alert = alert_naming(
        "big", 1, *(event["event"]["id"] for event in named), timestamp="2026-10-13T14:00:00.000Z"
    )
    target = synthetic_event("target-1", "2026-10-13T15:00:00.000Z", "target", "file")
    naming_target = [
        alert_naming("many", n, "target-1", timestamp=f"2026-10-13T15:01:{n % 60:02d}.000Z")
        for n in range(55)
    ]
    await index_extra_events(view_stack, [*named, big_alert, target, *naming_target])

    alert_detail = await detail_ok(view_stack, big_alert["event"]["id"])
    target_detail = await detail_ok(view_stack, "target-1")

    assert len(alert_detail["related"]["references"]["items"]) == 50
    assert alert_detail["related"]["references"]["total"] == 60
    assert len(target_detail["related"]["referenced_by"]["items"]) == 50
    assert target_detail["related"]["referenced_by"]["total"] == 55


async def test_an_alert_naming_an_event_that_is_gone_counts_only_what_exists(
    view_stack: ViewStack,
) -> None:
    alert = alert_naming("dangling", 1, "never-indexed-1", timestamp="2026-10-13T13:00:00.000Z")
    await index_extra_events(view_stack, [alert])

    detail = await detail_ok(view_stack, alert["event"]["id"])

    assert detail["related"]["references"] == {"items": [], "total": 0}


async def test_an_unknown_event_is_a_404_in_the_error_envelope(view_stack: ViewStack) -> None:
    response = await get_event(view_stack, "no/such:event")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


async def test_an_unknown_analysis_is_a_404(view_stack: ViewStack) -> None:
    response = await get_event(view_stack, "anything", analysis_id=999_999)

    assert response.status_code == 404
    assert "999999" in response.json()["error"]["message"]


async def test_an_analysis_with_no_index_has_no_such_event(view_stack: ViewStack) -> None:
    bare = await add_analysis_without_index(view_stack)

    response = await get_event(view_stack, "anything", analysis_id=bare)

    assert response.status_code == 404
