from typing import Any
from urllib.parse import quote

import pytest

from app.ingest.ingester import ReportIngester
from tests.ingest.conftest import FULL_REPORT
from tests.integration.views.conftest import ViewStack
from tests.integration.views.conftest import view_stack as view_stack  # noqa: PLC0414
from tests.integration.views.helpers import indexed_events

pytestmark = pytest.mark.integration

MISSING_PID = 999_999


async def a_process_event(stack: ViewStack) -> dict[str, Any]:
    events = await indexed_events(stack)
    return next(event for event in events.values() if event.get("process", {}).get("entity_id"))


async def annotate(stack: ViewStack, kind: str, ref: str, tag: str, note: str) -> None:
    base = f"/api/analyses/{stack.analysis_id}"
    target = {"target_type": kind, "target_ref": ref}
    assert (await stack.client.post(f"{base}/tags", json={"tag": tag, **target})).status_code == 201
    assert (
        await stack.client.post(f"{base}/notes", json={"body": note, **target})
    ).status_code == 201


async def read_annotations(stack: ViewStack) -> dict[str, Any]:
    response = await stack.client.get(f"/api/analyses/{stack.analysis_id}/annotations")
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def orphaned_by_ref(annotations: dict[str, Any]) -> dict[str, bool]:
    return {item["target_ref"]: item["orphaned"] for item in annotations["tags"]}


async def test_an_event_and_a_pid_the_index_holds_are_not_orphaned_and_missing_ones_are(
    view_stack: ViewStack,
) -> None:
    source = await a_process_event(view_stack)
    event_id, pid = source["event"]["id"], str(source["process"]["pid"])
    await annotate(view_stack, "event", event_id, "c2", "real event")
    await annotate(view_stack, "event", "no-such-event", "c2", "gone event")
    await annotate(view_stack, "process", pid, "dropper", "real process")
    await annotate(view_stack, "process", str(MISSING_PID), "dropper", "gone process")

    annotations = await read_annotations(view_stack)

    assert orphaned_by_ref(annotations) == {
        event_id: False,
        "no-such-event": True,
        pid: False,
        str(MISSING_PID): True,
    }
    assert {note["target_ref"]: note["orphaned"] for note in annotations["notes"]} == (
        orphaned_by_ref(annotations)
    )


async def test_a_reingest_keeps_the_annotations_and_the_event_detail_still_shows_them(
    view_stack: ViewStack,
) -> None:
    source = await a_process_event(view_stack)
    event_id = source["event"]["id"]
    await annotate(view_stack, "event", event_id, "c2", "beacon")
    before = await read_annotations(view_stack)

    await ReportIngester(view_stack.index).ingest(view_stack.analysis_id, FULL_REPORT)

    assert await read_annotations(view_stack) == before
    detail = await view_stack.client.get(
        f"/api/analyses/{view_stack.analysis_id}/events/{quote(event_id, safe='')}"
    )
    assert detail.status_code == 200
    assert [tag["tag"] for tag in detail.json()["annotations"]["tags"]] == ["c2"]
    assert [note["body"] for note in detail.json()["annotations"]["notes"]] == ["beacon"]


async def test_annotations_of_events_that_left_the_index_are_kept_and_marked_orphaned(
    view_stack: ViewStack,
) -> None:
    source = await a_process_event(view_stack)
    event_id = source["event"]["id"]
    await annotate(view_stack, "event", event_id, "c2", "beacon")
    await view_stack.index.drop(view_stack.analysis_id)

    annotations = await read_annotations(view_stack)

    assert orphaned_by_ref(annotations) == {event_id: True}
    assert [note["body"] for note in annotations["notes"]] == ["beacon"]


async def test_the_process_view_shows_the_tags_and_notes_of_each_pid(
    view_stack: ViewStack,
) -> None:
    source = await a_process_event(view_stack)
    pid = source["process"]["pid"]
    await annotate(view_stack, "process", str(pid), "dropper", "stage two")

    response = await view_stack.client.get(f"/api/analyses/{view_stack.analysis_id}/processes")

    assert response.status_code == 200
    marked = [
        (node["tags"], node["note_count"])
        for node in _all_nodes(response.json()["roots"])
        if node["pid"] == pid
    ]
    assert marked[0] == (["dropper"], 1)


def _all_nodes(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [found for node in nodes for found in [node, *_all_nodes(node["children"])]]
