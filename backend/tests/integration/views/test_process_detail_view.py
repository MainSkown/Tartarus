from collections import Counter
from typing import Any

import pytest

from tests.integration.views.conftest import ViewStack
from tests.integration.views.fixture_events import (
    BENIGN_PID,
    CMD_PID,
    events_where,
    of_pid,
)
from tests.integration.views.helpers import (
    get_view,
    index_extra_events,
    process_fields,
    synthetic_event,
)

pytestmark = pytest.mark.integration

SEMANTIC_LANES = {"process", "file", "registry", "network"}
LOAD_ACTIONS = {"LdrLoadDll", "DllLoadNotification"}


async def detail(stack: ViewStack, pid: int) -> dict[str, Any]:
    return await get_view(stack, f"processes/{pid}")


async def test_the_detail_repeats_the_node_fields_of_the_tree(view_stack: ViewStack) -> None:
    found = await detail(view_stack, CMD_PID)

    assert (found["pid"], found["name"], found["ppid"]) == (CMD_PID, "cmd.exe", BENIGN_PID)
    assert found["command_line"] == "cmd.exe /c ver"
    assert found["detection_count"] == 2
    assert "children" not in found


async def test_top_apis_are_the_most_called_with_their_counts(view_stack: ViewStack) -> None:
    found = await detail(view_stack, BENIGN_PID)

    expected = Counter(
        event["api"]["name"] for event in events_where(of_pid(BENIGN_PID)) if "api" in event
    )
    returned = {api["name"]: api["count"] for api in found["top_apis"]}
    counts = [api["count"] for api in found["top_apis"]]
    cutoff = counts[-1]
    assert len(returned) == 15
    assert counts == sorted(counts, reverse=True)
    assert all(expected[name] == count for name, count in returned.items())
    assert {name for name, count in expected.items() if count > cutoff} <= set(returned)


async def test_modules_are_the_distinct_libraries_the_process_loaded(
    view_stack: ViewStack,
) -> None:
    found = await detail(view_stack, BENIGN_PID)

    loads = [
        event["api"]["arguments"]
        for event in events_where(of_pid(BENIGN_PID))
        if event.get("api", {}).get("name") in LOAD_ACTIONS
        and event["api"]["arguments"].get("NotificationReason", "load") == "load"
    ]
    addresses = {args.get("BaseAddress") or args.get("DllBase") for args in loads}
    modules = {module["base_address"]: module for module in found["modules"]}
    assert set(modules) == addresses
    assert len(found["modules"]) == len(addresses)
    assert modules["0x7ffd9f590000"]["name"] == "SHELL32.dll"
    assert modules["0x7ffd9b920000"]["name"] == "mswsock.dll"
    assert modules["0x7ffd9b920000"]["path"] == r"C:\Windows\System32\mswsock.dll"
    assert modules["0x7ffd9d790000"]["name"] == "wintypes"
    assert modules["0x7ffd9d790000"]["path"] == r"C:\WINDOWS\System32\wintypes"


async def test_events_are_the_derived_ones_newest_first_with_a_total(
    view_stack: ViewStack,
) -> None:
    found = await detail(view_stack, BENIGN_PID)

    expected = events_where(
        lambda event: of_pid(BENIGN_PID)(event) and event["tartarus"]["lane"] in SEMANTIC_LANES
    )
    assert found["event_total"] == len(expected)
    assert len(found["events"]) == len(expected)
    times = [row["time"] for row in found["events"]]
    assert times == sorted(times, reverse=True)
    created = next(row for row in found["events"] if row["action"] == "file-created")
    assert created["lane"] == "file"
    assert created["summary"].endswith("tartarus-benign.txt")
    assert created["event_id"]
    assert not any(row["lane"] == "api" for row in found["events"])


async def test_only_the_200_most_recent_events_are_listed(view_stack: ViewStack) -> None:
    process = process_fields(view_stack, BENIGN_PID, "benign.exe", "2026-10-13T12:12:41.164Z", 4336)
    extra = [
        synthetic_event(
            f"bulk-{number}",
            f"2026-10-13T12:13:{number % 60:02d}.{number:03d}Z",
            "file-written",
            "file",
            process=process,
        )
        for number in range(250)
    ]
    await index_extra_events(view_stack, extra)

    found = await detail(view_stack, BENIGN_PID)

    assert len(found["events"]) == 200
    assert found["event_total"] == 250 + len(
        events_where(
            lambda event: of_pid(BENIGN_PID)(event) and event["tartarus"]["lane"] in SEMANTIC_LANES
        )
    )
    assert found["events"][0]["event_id"].startswith("bulk-")


async def test_an_unknown_pid_is_a_404(view_stack: ViewStack) -> None:
    response = await view_stack.client.get(f"/api/analyses/{view_stack.analysis_id}/processes/1")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


async def test_the_detail_of_an_unknown_analysis_is_a_404(view_stack: ViewStack) -> None:
    response = await view_stack.client.get("/api/analyses/99999/processes/10116")

    assert response.status_code == 404
