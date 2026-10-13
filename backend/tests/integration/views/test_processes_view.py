from typing import Any

import pytest

from tests.integration.views.conftest import ViewStack
from tests.integration.views.fixture_events import (
    BENIGN_PID,
    CMD_PID,
    events_where,
    instant,
    of_pid,
)
from tests.integration.views.helpers import (
    add_analysis_without_index,
    get_view,
    index_extra_events,
    process_fields,
    synthetic_event,
)

pytestmark = pytest.mark.integration


async def processes(stack: ViewStack) -> dict[str, Any]:
    return await get_view(stack, "processes")


async def test_the_tree_has_the_sample_as_root_and_cmd_as_its_child(view_stack: ViewStack) -> None:
    tree = await processes(view_stack)

    assert tree["total"] == 2
    [root] = tree["roots"]
    assert (root["pid"], root["name"]) == (BENIGN_PID, "benign.exe")
    assert root["executable"] == r"C:\Users\Analyst\AppData\Local\Temp\benign.exe"
    assert root["ppid"] == 4336
    [child] = root["children"]
    assert (child["pid"], child["name"], child["ppid"]) == (CMD_PID, "cmd.exe", BENIGN_PID)
    assert child["command_line"] == "cmd.exe /c ver"
    assert child["executable"] == r"C:\Windows\System32\cmd.exe"
    assert child["children"] == []


async def test_a_process_lives_from_its_first_record_to_its_termination(
    view_stack: ViewStack,
) -> None:
    [root] = (await processes(view_stack))["roots"]
    [child] = root["children"]

    assert instant(root["start"]) == instant("2026-10-13T12:12:41.164Z")
    assert instant(root["end"]) == instant("2026-10-13T12:12:42.258Z")
    assert instant(child["start"]) == instant("2026-10-13T12:12:41.613Z")
    assert instant(child["end"]) == instant("2026-10-13T12:12:42.019Z")


async def test_integrity_is_null_because_no_source_reports_it(view_stack: ViewStack) -> None:
    [root] = (await processes(view_stack))["roots"]

    assert root["integrity"] is None
    assert root["children"][0]["integrity"] is None


async def test_lane_counts_add_up_to_the_events_of_each_process(view_stack: ViewStack) -> None:
    [root] = (await processes(view_stack))["roots"]
    [child] = root["children"]

    for node in (root, child):
        assert sum(node["event_counts_by_lane"].values()) == len(events_where(of_pid(node["pid"])))
    assert root["event_counts_by_lane"]["file"] == 2
    assert root["event_counts_by_lane"]["registry"] == 2
    assert "file" not in child["event_counts_by_lane"]


async def test_detections_count_for_the_processes_whose_calls_raised_them(
    view_stack: ViewStack,
) -> None:
    [root] = (await processes(view_stack))["roots"]
    [child] = root["children"]

    assert (root["detection_count"], root["max_severity"]) == (5, "high")
    assert (child["detection_count"], child["max_severity"]) == (2, "medium")


async def test_a_process_without_detections_has_no_severity(view_stack: ViewStack) -> None:
    ghost = synthetic_event(
        "ghost-1",
        "2026-10-13T12:12:43.000Z",
        "process-created",
        "process",
        process=process_fields(view_stack, 7777, "ghost.exe", "2026-10-13T12:12:43.000Z", 4),
    )
    await index_extra_events(view_stack, [ghost])

    roots = (await processes(view_stack))["roots"]
    found = next(node for node in roots if node["pid"] == 7777)

    assert (found["detection_count"], found["max_severity"]) == (0, None)
    assert found["ppid"] == 4


async def test_network_hosts_come_from_events_attributed_to_the_process(
    view_stack: ViewStack,
) -> None:
    [root] = (await processes(view_stack))["roots"]

    assert "tartarus-selftest.example" in root["network_hosts"]
    assert root["children"][0]["network_hosts"] == []


async def test_injected_into_lists_the_targets_of_inject_events(view_stack: ViewStack) -> None:
    injector = process_fields(
        view_stack, BENIGN_PID, "benign.exe", "2026-10-13T12:12:41.164Z", 4336
    )
    event = synthetic_event(
        "inject-1",
        "2026-10-13T12:12:42.100Z",
        "inject-write-memory",
        "process",
        process=injector,
        tartarus={
            "analysis_id": 6,
            "lane": "process",
            "phase": "final",
            "summary": "inject",
            "inject": {"target_pid": CMD_PID},
        },
    )
    await index_extra_events(view_stack, [event])

    [root] = (await processes(view_stack))["roots"]

    assert root["injected_into"] == [CMD_PID]
    assert root["children"][0]["injected_into"] == []


async def test_an_unknown_analysis_is_a_404_in_the_error_envelope(view_stack: ViewStack) -> None:
    response = await view_stack.client.get("/api/analyses/99999/processes")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


async def test_an_analysis_without_an_index_has_an_empty_tree(view_stack: ViewStack) -> None:
    bare = await add_analysis_without_index(view_stack)

    assert await get_view(view_stack, "processes", bare) == {"roots": [], "total": 0}
