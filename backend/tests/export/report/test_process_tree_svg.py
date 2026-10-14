import math
import random
import re
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from typing import Any

import pytest

from app.db.models.analysis import Severity
from app.export.report.process_tree_svg import (
    BOX_HEIGHT,
    MAX_DEPTH,
    MAX_NAME_CHARS,
    MAX_ROWS,
    PRINT_PALETTE,
    ROW_HEIGHT,
    ROWS_PER_WINDOW,
    SCREEN_PALETTE,
    TreeDrawing,
    TreeRow,
    layout_rows,
)
from app.schemas.views_events import ProcessNode

SVG = "{http://www.w3.org/2000/svg}"
NODE_BOX_STROKE_WIDTH = "2"


def node(pid: int, children: list[ProcessNode] | None = None, **changes: Any) -> ProcessNode:
    fields: dict[str, Any] = {
        "entity_id": f"1:{pid}",
        "pid": pid,
        "ppid": None,
        "name": f"p{pid}.exe",
        "executable": None,
        "command_line": None,
        "start": datetime(2026, 1, 1, tzinfo=UTC),
        "end": None,
        "integrity": None,
        "max_severity": changes.pop("severity", None),
        "detection_count": changes.pop("detections", 0),
        "injected_into": [],
        "network_hosts": [],
        "event_counts_by_lane": {},
        "children": children or [],
    }
    return ProcessNode(**{**fields, **changes})


def chain(length: int, first_pid: int = 1) -> ProcessNode:
    deepest = node(first_pid + length - 1)
    for pid in range(first_pid + length - 2, first_pid - 1, -1):
        deepest = node(pid, [deepest])
    return deepest


def fan(children: int) -> ProcessNode:
    return node(1, [node(100 + n) for n in range(children)])


def random_tree(size: int, seed: int) -> ProcessNode:
    generator = random.Random(seed)  # noqa: S311
    nodes = [node(1)]
    for pid in range(2, size + 1):
        generator.choice(nodes).children.append(added := node(pid))
        nodes.append(added)
    return nodes[0]


def count(nodes: list[ProcessNode]) -> int:
    return sum(1 + count(each.children) for each in nodes)


def shown_pids(rows: tuple[TreeRow, ...]) -> list[int]:
    return [row.pid for row in rows if row.pid is not None]


def hidden_total(rows: tuple[TreeRow, ...]) -> int:
    return sum(row.hidden for row in rows)


def parse(svg: str) -> ET.Element:
    return ET.fromstring(svg)  # noqa: S314


def labels(svg: str) -> list[str]:
    return [
        text.text or "" for text in parse(svg).iter(f"{SVG}text") if text.get("font-size") == "12"
    ]


def box_rects(svg: str) -> list[ET.Element]:
    return [
        rect
        for rect in parse(svg).iter(f"{SVG}rect")
        if rect.get("stroke-width") == NODE_BOX_STROKE_WIDTH
    ]


def view_box(svg: str) -> tuple[float, float, float, float]:
    x, y, width, height = (float(part) for part in parse(svg).get("viewBox", "").split())
    return x, y, width, height


def test_rows_follow_the_tree_depth_first_with_indent_per_level() -> None:
    root = node(1, [node(2, [node(3)]), node(4)])

    rows = layout_rows([root])

    assert [(row.depth, row.label, row.parent) for row in rows] == [
        (0, "p1.exe (1)", None),
        (1, "p2.exe (2)", 0),
        (2, "p3.exe (3)", 1),
        (1, "p4.exe (4)", 0),
    ]


def test_a_long_name_is_cut_with_an_ellipsis_inside_the_limit() -> None:
    rows = layout_rows([node(7, name="x" * 300)])

    assert rows[0].label == "x" * (MAX_NAME_CHARS - 1) + "… (7)"


def test_a_name_at_the_limit_is_not_cut() -> None:
    name = "y" * MAX_NAME_CHARS

    assert layout_rows([node(7, name=name)])[0].label == f"{name} (7)"


def test_a_process_without_a_name_is_called_unknown() -> None:
    rows = layout_rows([node(7).model_copy(update={"name": None})])

    assert rows[0].label == "unknown (7)"


def test_a_process_with_detections_shows_its_highest_severity_and_their_count() -> None:
    rows = layout_rows([node(1, severity=Severity.HIGH, detections=3), node(2)])

    assert [(row.severity, row.detections) for row in rows] == [(Severity.HIGH, 3), (None, 0)]


def test_the_sample_process_is_marked() -> None:
    rows = layout_rows([node(1, [node(2)])], sample_pid=2)

    assert [row.sample for row in rows] == [False, True]


def test_an_injecting_process_lists_its_targets_and_the_target_is_marked() -> None:
    rows = layout_rows([node(1, [node(2)], injected_into=[2]), node(3)])

    assert [(row.injects, row.injection_target) for row in rows] == [
        ((2,), False),
        ((), True),
        ((), False),
    ]


def test_an_injection_target_is_marked_even_when_its_injector_is_not_drawn() -> None:
    root = node(1, [node(n) for n in range(2, 300)], injected_into=[250])
    rows = layout_rows([root], max_rows=10)

    assert next(row for row in rows if row.pid == 250).injection_target


def test_a_deep_chain_stops_at_the_depth_limit_and_says_how_many_it_left_out() -> None:
    rows = layout_rows([chain(30)])

    assert max(row.depth for row in rows if row.pid is not None) == MAX_DEPTH - 1
    assert rows[-1].hidden == 30 - MAX_DEPTH
    assert rows[-1].label == f"+{30 - MAX_DEPTH} more"
    assert rows[-1].depth == MAX_DEPTH


def test_a_tree_within_both_limits_is_drawn_whole() -> None:
    rows = layout_rows([chain(MAX_DEPTH)])

    assert len(rows) == MAX_DEPTH
    assert hidden_total(rows) == 0


def test_the_row_cap_counts_the_more_rows_too() -> None:
    rows = layout_rows([fan(400)])

    assert len(rows) == MAX_ROWS
    assert rows[-1].hidden > 0


def test_a_tree_of_exactly_the_cap_is_not_cut() -> None:
    rows = layout_rows([fan(MAX_ROWS - 1)])

    assert len(rows) == MAX_ROWS
    assert hidden_total(rows) == 0


def test_one_node_over_the_cap_is_replaced_by_a_more_row_that_fits() -> None:
    rows = layout_rows([fan(MAX_ROWS)])

    assert len(rows) == MAX_ROWS
    assert hidden_total(rows) == 2


@pytest.mark.parametrize("size", [50, 121, 400, 2000])
@pytest.mark.parametrize("seed", [1, 2, 3])
def test_a_random_tree_keeps_to_the_cap_and_accounts_for_every_process(
    size: int, seed: int
) -> None:
    root = random_tree(size, seed)

    rows = layout_rows([root])

    assert len(rows) <= MAX_ROWS
    assert len(shown_pids(rows)) + hidden_total(rows) == count([root])


def test_a_process_with_a_detection_survives_the_cap_with_its_ancestors() -> None:
    flagged = node(999, severity=Severity.CRITICAL, detections=1)
    deep = node(2, [node(3, [node(4, [flagged])])])
    root = node(1, [*[node(100 + n) for n in range(300)], deep])

    rows = layout_rows([root])

    assert {1, 2, 3, 4, 999} <= set(shown_pids(rows))
    assert len(rows) <= MAX_ROWS


def test_many_roots_are_capped_with_a_more_row_at_the_top_level() -> None:
    rows = layout_rows([node(n) for n in range(1, 300)])

    assert len(rows) == MAX_ROWS
    assert (rows[-1].depth, rows[-1].parent) == (0, None)
    assert len(shown_pids(rows)) + rows[-1].hidden == 299


def test_a_more_row_hangs_under_the_process_whose_children_it_hides() -> None:
    rows = layout_rows([node(1, [node(2, [node(3), node(4)])])], max_rows=3)

    assert [(row.label, row.depth, row.parent) for row in rows] == [
        ("p1.exe (1)", 0, None),
        ("p2.exe (2)", 1, 0),
        ("+2 more", 2, 1),
    ]


def test_an_empty_tree_has_no_rows_and_still_draws() -> None:
    rows = layout_rows([])

    svg = TreeDrawing(rows, SCREEN_PALETTE).svg()

    assert rows == ()
    assert parse(svg).tag == f"{SVG}svg"


def test_the_svg_is_well_formed_and_its_viewbox_is_its_size() -> None:
    svg = TreeDrawing(layout_rows([node(1, [node(2)])]), PRINT_PALETTE).svg()

    root = parse(svg)
    _, _, width, height = view_box(svg)
    assert (float(root.get("width", "")), float(root.get("height", ""))) == (width, height)


def test_the_height_grows_with_the_rows_and_the_width_with_depth_and_name() -> None:
    small = view_box(TreeDrawing(layout_rows([node(1)]), PRINT_PALETTE).svg())
    tall = view_box(TreeDrawing(layout_rows([fan(10)]), PRINT_PALETTE).svg())
    deep = view_box(TreeDrawing(layout_rows([chain(8)]), PRINT_PALETTE).svg())

    assert tall[3] > small[3]
    assert deep[2] > tall[2] > small[2]


def test_every_label_and_marker_fits_inside_the_viewbox() -> None:
    flagged = node(1, [chain(40, 10)], name="n" * 80, severity=Severity.CRITICAL, detections=99)
    flagged.injected_into.extend([10, 11, 12, 13, 14])
    svg = TreeDrawing(layout_rows([flagged], sample_pid=1), PRINT_PALETTE).svg()
    _, _, width, height = view_box(svg)

    for rect in parse(svg).iter(f"{SVG}rect"):
        if rect.get("width", "").endswith("%"):
            continue
        assert float(rect.get("x", 0)) + float(rect.get("width", 0)) <= width
        assert float(rect.get("y", 0)) + float(rect.get("height", 0)) <= height


def test_the_widest_tree_stays_readable_on_an_a4_page() -> None:
    """A page body is about 690 px wide; past 960 px the text would print under 6 pt."""
    deepest = node(
        MAX_DEPTH,
        name="n" * 80,
        severity=Severity.CRITICAL,
        detections=99,
        injected_into=[1, 2, 3, 4, 5],
    )
    top = chain(MAX_DEPTH - 1)
    last = top
    while last.children:
        last = last.children[0]
    last.children.append(deepest)
    rows = layout_rows([top], sample_pid=MAX_DEPTH)
    assert rows[-1].depth == MAX_DEPTH - 1
    assert rows[-1].sample

    width = view_box(TreeDrawing(rows, PRINT_PALETTE).svg())[2]

    assert 700 < width <= 960


def test_hostile_text_in_a_name_stays_text() -> None:
    hostile = '</text><script>alert(1)</script><a href="javascript:x">"&'
    svg = TreeDrawing(layout_rows([node(1, name=hostile)]), PRINT_PALETTE).svg()

    root = parse(svg)
    assert not list(root.iter(f"{SVG}script"))
    assert "<script" not in svg
    assert "<" not in re.sub(r"<[^<>]*>", "", svg)
    assert any("script" in text for text in labels(svg))


def test_the_two_palettes_differ_but_share_the_severity_colours() -> None:
    rows = layout_rows([node(1, severity=Severity.HIGH, detections=1)])

    screen = TreeDrawing(rows, SCREEN_PALETTE).svg()
    printed = TreeDrawing(rows, PRINT_PALETTE).svg()

    assert screen != printed
    assert SCREEN_PALETTE.background != PRINT_PALETTE.background
    assert "#f97316" in screen
    assert "#f97316" in printed


def test_a_severity_is_written_as_text_not_only_drawn_as_a_colour() -> None:
    svg = TreeDrawing(
        layout_rows([node(1, severity=Severity.HIGH, detections=5)]), PRINT_PALETTE
    ).svg()

    assert "HIGH 5" in svg


def test_the_windows_cover_every_row_once_in_order() -> None:
    rows = layout_rows([random_tree(400, 5)])
    windows = TreeDrawing(rows, PRINT_PALETTE).windows()

    assert len(windows) == math.ceil(len(rows) / ROWS_PER_WINDOW)
    drawn = [label for window in windows for label in labels(window)]
    assert drawn == [row.label for row in rows]


def test_a_window_holds_at_most_the_requested_rows() -> None:
    rows = layout_rows([random_tree(400, 5)])

    windows = TreeDrawing(rows, PRINT_PALETTE).windows(rows_per_window=10)

    assert all(len(labels(window)) <= 10 for window in windows)
    assert len(windows) == math.ceil(len(rows) / 10)


def test_a_tree_shorter_than_a_window_is_one_window_equal_to_the_whole_drawing() -> None:
    rows = layout_rows([fan(5)])
    drawing = TreeDrawing(rows, PRINT_PALETTE)

    assert drawing.windows() == [drawing.svg()]


def test_a_window_never_cuts_a_box_in_half() -> None:
    rows = layout_rows([random_tree(400, 9)])

    for window in TreeDrawing(rows, PRINT_PALETTE).windows():
        _, _, _, height = view_box(window)
        for rect in box_rects(window):
            top = float(rect.get("y", 0))
            assert top >= 0
            assert top + float(rect.get("height", 0)) <= height


def test_a_window_is_cut_in_the_gap_with_room_left_above_and_below_its_boxes() -> None:
    gap = (ROW_HEIGHT - BOX_HEIGHT) / 2
    rows = layout_rows([random_tree(400, 9)])

    for window in TreeDrawing(rows, PRINT_PALETTE).windows():
        _, _, _, height = view_box(window)
        boxes = box_rects(window)
        assert min(float(rect.get("y", 0)) for rect in boxes) >= gap
        assert max(float(rect.get("y", 0)) + BOX_HEIGHT for rect in boxes) <= height - gap


def test_every_window_is_as_wide_as_the_whole_tree_so_the_text_scales_alike() -> None:
    rows = layout_rows([random_tree(400, 9)])
    drawing = TreeDrawing(rows, PRINT_PALETTE)

    widths = {view_box(window)[2] for window in drawing.windows()}

    assert widths == {view_box(drawing.svg())[2]}


def test_a_connector_to_a_parent_on_an_earlier_window_starts_at_the_top_of_the_window() -> None:
    rows = layout_rows([fan(60)])
    second = TreeDrawing(rows, PRINT_PALETTE).windows()[1]

    paths = [path.get("d", "") for path in parse(second).iter(f"{SVG}path")]

    assert paths
    assert all(re.match(r"M[\d.]+ 0(\.0)? ", path) for path in paths)


def test_a_window_holds_only_its_own_rows_not_the_whole_tree_again() -> None:
    rows = layout_rows([random_tree(400, 5)])
    drawing = TreeDrawing(rows, PRINT_PALETTE)

    assert sum(len(window) for window in drawing.windows()) < 1.6 * len(drawing.svg())


def test_a_window_needs_at_least_one_row() -> None:
    with pytest.raises(ValueError, match="rows_per_window"):
        TreeDrawing(layout_rows([node(1)]), PRINT_PALETTE).windows(rows_per_window=0)
