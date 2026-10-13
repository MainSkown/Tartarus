from datetime import UTC, datetime

from app.schemas.views_events import ProcessNode, ProcessSummary
from app.views.processes import DetectionStats, attribute_alerts, build_tree


def summary(pid: int, ppid: int | None, second: int) -> ProcessSummary:
    return ProcessSummary(
        entity_id=f"1:{pid}@{second}",
        pid=pid,
        ppid=ppid,
        name=f"p{pid}.exe",
        executable=None,
        command_line=None,
        start=datetime(2026, 1, 1, 0, 0, second, tzinfo=UTC),
        end=None,
        integrity=None,
        max_severity=None,
        detection_count=0,
        injected_into=[],
        network_hosts=[],
        event_counts_by_lane={},
    )


def shape(nodes: list[ProcessNode]) -> list[tuple[int, list[object]]]:
    return [(node.pid, shape(node.children)) for node in nodes]


def test_a_process_whose_parent_is_not_in_the_set_is_a_root() -> None:
    tree = build_tree([summary(10, 4, 1), summary(20, 10, 2)])

    assert shape(tree) == [(10, [(20, [])])]


def test_children_are_ordered_by_start_time() -> None:
    tree = build_tree([summary(1, None, 0), summary(30, 1, 3), summary(20, 1, 2)])

    assert shape(tree) == [(1, [(20, []), (30, [])])]


def test_a_reused_pid_parents_only_the_children_started_after_it() -> None:
    tree = build_tree(
        [
            summary(5, None, 1),
            summary(9, 5, 2),
            summary(5, None, 10),
            summary(11, 5, 11),
        ]
    )

    assert shape(tree) == [(5, [(9, [])]), (5, [(11, [])])]


def test_a_process_that_names_itself_as_parent_is_a_root_and_no_cycle_forms() -> None:
    tree = build_tree([summary(7, 7, 1), summary(8, 9, 1), summary(9, 8, 1)])

    assert shape(tree) == [(7, []), (8, [(9, [])])]


def test_an_empty_set_has_an_empty_tree() -> None:
    assert build_tree([]) == []


def alert(event_id: str, severity: int, related: list[str]) -> dict[str, object]:
    return {"event": {"id": event_id, "severity": severity}, "related": {"events": related}}


def test_an_alert_counts_for_every_process_that_owns_a_referenced_call() -> None:
    stats = attribute_alerts(
        [alert("a1", 2, ["c1", "c2"]), alert("a2", 3, ["c2"])],
        {"c1": "proc-a", "c2": "proc-b"},
    )

    assert stats == {"proc-a": DetectionStats(1, 2), "proc-b": DetectionStats(2, 3)}


def test_an_alert_counts_once_per_process_however_many_calls_it_references() -> None:
    stats = attribute_alerts(
        [alert("a1", 1, ["c1", "c2", "c3"])], {"c1": "p", "c2": "p", "c3": "p"}
    )

    assert stats == {"p": DetectionStats(1, 1)}


def test_an_alert_without_resolvable_calls_belongs_to_no_process() -> None:
    assert attribute_alerts([alert("a1", 2, []), alert("a2", 2, ["gone"])], {}) == {}


def test_an_alert_that_names_its_own_process_belongs_to_it() -> None:
    own: dict[str, object] = {
        "event": {"id": "a1", "severity": 3},
        "process": {"entity_id": "proc-a"},
    }

    assert attribute_alerts([own], {}) == {"proc-a": DetectionStats(1, 3)}
