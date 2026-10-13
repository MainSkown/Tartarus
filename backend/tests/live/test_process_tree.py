from typing import Any

from app.live.messages import LiveProcess, ProcessData
from app.live.process_tree import ProcessTree
from tests.live.events import make_event


def observe(tree: ProcessTree, *events: dict[str, Any]) -> list[ProcessData]:
    return [delta for event in events for delta in tree.observe(event)]


def test_the_first_event_of_a_process_adds_it_to_the_tree() -> None:
    tree = ProcessTree()

    deltas = observe(tree, make_event("api", pid=9708, name="benign.exe", parent_pid=4))

    assert [(d.op, d.node.pid) for d in deltas] == [("add", 9708)]
    assert deltas[0].node == LiveProcess(
        pid=9708,
        ppid=4,
        name="benign.exe",
        executable="C:\\Temp\\sample.exe",
        command_line="sample.exe",
        start="2026-10-13T10:59:00.000Z",
    )


def test_a_process_already_known_adds_nothing_when_an_event_tells_nothing_new() -> None:
    tree = ProcessTree()
    observe(tree, make_event("api", pid=7))

    assert observe(tree, make_event("file", pid=7), make_event("api", pid=7)) == []


def test_an_event_that_fills_in_a_missing_detail_updates_the_node() -> None:
    tree = ProcessTree()
    observe(tree, make_event("api", pid=7, command_line=None))

    deltas = observe(tree, make_event("process", pid=7, action="process-created"))

    assert [(d.op, d.node.command_line) for d in deltas] == [("update", "sample.exe")]


def test_a_detail_already_known_is_not_overwritten_by_a_later_blank() -> None:
    tree = ProcessTree()
    observe(tree, make_event("api", pid=7))

    assert observe(tree, make_event("api", pid=7, command_line=None)) == []
    assert tree.nodes[7].command_line == "sample.exe"


def test_terminating_a_process_ends_its_node_with_the_event_time() -> None:
    tree = ProcessTree()
    observe(tree, make_event("api", pid=7))

    deltas = observe(
        tree,
        make_event(
            "process", pid=7, action="process-terminated", timestamp="2026-10-13T11:05:00.000Z"
        ),
    )

    assert [(d.op, d.node.end) for d in deltas] == [("end", "2026-10-13T11:05:00.000Z")]


def test_a_process_ends_once() -> None:
    tree = ProcessTree()
    ended = make_event("process", pid=7, action="process-terminated")
    observe(tree, make_event("api", pid=7), ended)

    assert observe(tree, ended) == []


def test_a_process_first_seen_terminating_is_added_then_ended() -> None:
    tree = ProcessTree()

    deltas = observe(tree, make_event("process", pid=7, action="process-terminated"))

    assert [d.op for d in deltas] == ["add", "end"]


def test_a_pid_reused_by_a_new_process_starts_a_new_node() -> None:
    tree = ProcessTree()
    observe(
        tree,
        make_event("api", pid=7, start="2026-10-13T10:00:00.000Z"),
        make_event("process", pid=7, action="process-terminated"),
    )

    deltas = observe(tree, make_event("api", pid=7, start="2026-10-13T10:30:00.000Z"))

    assert [(d.op, d.node.start, d.node.end) for d in deltas] == [
        ("add", "2026-10-13T10:30:00.000Z", None)
    ]


def test_an_event_without_a_pid_changes_nothing() -> None:
    tree = ProcessTree()
    event = make_event("api")
    del event["process"]["pid"]

    assert observe(tree, event) == []
    assert tree.nodes == {}


def test_the_snapshot_lists_every_node_by_pid() -> None:
    tree = ProcessTree()
    observe(tree, make_event("api", pid=9), make_event("api", pid=3))

    assert [node.pid for node in tree.snapshot()] == [3, 9]
