"""The report's process tree: a plain indented tree drawn as static SVG.

`layout_rows` decides which processes fit; `TreeDrawing` draws them whole (the HTML report) or
cut into windows between rows (the PDF, where one SVG cannot break across pages).
"""

import xml.etree.ElementTree as ET
from collections.abc import Sequence
from dataclasses import dataclass, field

from pydantic import BaseModel, ConfigDict

from app.db.models.analysis import Severity
from app.export.report.theme import MONO_FONTS, SEVERITY_COLOURS
from app.schemas.views_events import ProcessNode

MAX_ROWS = 120
MAX_DEPTH = 12
MAX_NAME_CHARS = 30
ROWS_PER_WINDOW = 30
MAX_LISTED_TARGETS = 3

CHAR_WIDTH = 7.2  # a monospace advance is 0.6 em, drawn at 12 px
BADGE_CHAR_WIDTH = 6.6
BADGE_PADDING = 12
BADGE_GAP = 6
LABEL_PADDING = 16
ROW_HEIGHT = 28
BOX_HEIGHT = 22
INDENT = 22
PAD = 12
LABEL_SIZE = 12
BADGE_SIZE = 10
CONNECTOR_OFFSET = 10
INJECTION_COLOUR = SEVERITY_COLOURS[Severity.HIGH]
_VIRTUAL_ROOT = 0


@dataclass(frozen=True)
class TreePalette:
    background: str
    box_fill: str
    ink: str
    muted: str
    connector: str
    border: str


SCREEN_PALETTE = TreePalette(
    background="#0a0a0a",
    box_fill="#0a0a0a",
    ink="#ffffff",
    muted="#a3a3a3",
    connector="#0369a1",
    border="#38bdf8",
)
PRINT_PALETTE = TreePalette(
    background="#ffffff",
    box_fill="#ffffff",
    ink="#111827",
    muted="#6b7280",
    connector="#0369a1",
    border="#38bdf8",
)


class TreeRow(BaseModel):
    """One line of the drawing: a process, or a `+N more` line for what the limits left out."""

    model_config = ConfigDict(frozen=True)

    depth: int
    label: str
    pid: int | None = None
    severity: Severity | None = None
    detections: int = 0
    injects: tuple[int, ...] = ()
    injection_target: bool = False
    sample: bool = False
    hidden: int = 0
    parent: int | None = None


@dataclass
class _Node:
    index: int
    parent: int
    depth: int
    process: ProcessNode | None
    children: list[int] = field(default_factory=list)
    size: int = 1


def layout_rows(
    roots: Sequence[ProcessNode],
    sample_pid: int | None = None,
    max_rows: int = MAX_ROWS,
    max_depth: int = MAX_DEPTH,
) -> tuple[TreeRow, ...]:
    """The rows to draw, `max_rows` at most, `+N more` rows included, no deeper than `max_depth`.

    Past the limits the processes with detections, injections or the sample, and their
    ancestors, are kept first, then the rest from the top down.
    """
    nodes = _flatten(roots)
    targets = {pid for node in nodes[1:] for pid in _process_of(node).injected_into}
    kept = _Selection(nodes, max_rows).keep(_by_priority(nodes, targets, sample_pid, max_depth))
    emitter = _Emitter(nodes, kept, targets, sample_pid)
    emitter.emit(_VIRTUAL_ROOT, None)
    return tuple(emitter.rows)


def _flatten(roots: Sequence[ProcessNode]) -> list[_Node]:
    nodes = [_Node(_VIRTUAL_ROOT, _VIRTUAL_ROOT, -1, None)]
    pending = [(root, _VIRTUAL_ROOT, 0) for root in reversed(roots)]
    while pending:
        process, parent, depth = pending.pop()
        node = _Node(len(nodes), parent, depth, process)
        nodes.append(node)
        nodes[parent].children.append(node.index)
        pending.extend((child, node.index, depth + 1) for child in reversed(process.children))
    for node in reversed(nodes[1:]):
        nodes[node.parent].size += node.size
    return nodes


def _by_priority(
    nodes: Sequence[_Node], targets: set[int], sample_pid: int | None, max_depth: int
) -> list[int]:
    candidates = [node for node in nodes[1:] if node.depth < max_depth]
    return [
        node.index
        for node in sorted(
            candidates,
            key=lambda node: (not _flagged(node, targets, sample_pid), node.depth, node.index),
        )
    ]


def _process_of(node: _Node) -> ProcessNode:
    if node.process is None:
        raise LookupError("the top of the tree is not a process")
    return node.process


def _flagged(node: _Node, targets: set[int], sample_pid: int | None) -> bool:
    process = _process_of(node)
    return bool(
        process.detection_count
        or process.injected_into
        or process.pid in targets
        or process.pid == sample_pid
    )


class _Selection:
    """Grows the kept set while the rows it needs stay within the limit.

    A kept process costs a row, and one more row for the `+N more` line while any of its
    children is not kept; the top level has such a line for roots that are not kept.
    """

    def __init__(self, nodes: Sequence[_Node], max_rows: int) -> None:
        self._nodes = nodes
        self._max_rows = max_rows
        self._kept_children = [0] * len(nodes)
        self.kept = {_VIRTUAL_ROOT}
        self._rows = 1 if nodes[_VIRTUAL_ROOT].children else 0

    def keep(self, priority: Sequence[int]) -> set[int]:
        for index in priority:
            self._try_to_keep_with_ancestors(index)
        return self.kept

    def _try_to_keep_with_ancestors(self, index: int) -> None:
        missing = []
        while index not in self.kept:
            missing.append(index)
            index = self._nodes[index].parent
        added = []
        for each in reversed(missing):
            self._add(each)
            added.append(each)
        if self._rows > self._max_rows:
            for each in reversed(added):
                self._remove(each)

    def _add(self, index: int) -> None:
        node = self._nodes[index]
        parent = self._nodes[node.parent]
        self.kept.add(index)
        self._kept_children[node.parent] += 1
        self._rows += 1 + (1 if node.children else 0)
        if self._kept_children[node.parent] == len(parent.children):
            self._rows -= 1

    def _remove(self, index: int) -> None:
        node = self._nodes[index]
        parent = self._nodes[node.parent]
        if self._kept_children[node.parent] == len(parent.children):
            self._rows += 1
        self._kept_children[node.parent] -= 1
        self._rows -= 1 + (1 if node.children else 0)
        self.kept.discard(index)


class _Emitter:
    """Walks the kept processes depth-first into rows, each `+N more` row after its siblings."""

    def __init__(
        self, nodes: Sequence[_Node], kept: set[int], targets: set[int], sample_pid: int | None
    ) -> None:
        self._nodes = nodes
        self._kept = kept
        self._targets = targets
        self._sample_pid = sample_pid
        self.rows: list[TreeRow] = []

    def emit(self, index: int, parent_row: int | None) -> None:
        node = self._nodes[index]
        own_row = parent_row
        if node.process is not None:
            own_row = len(self.rows)
            self.rows.append(self._process_row(node, parent_row))
        for child in node.children:
            if child in self._kept:
                self.emit(child, own_row)
        hidden = sum(self._nodes[child].size for child in node.children if child not in self._kept)
        if hidden:
            self.rows.append(
                TreeRow(
                    depth=node.depth + 1, label=f"+{hidden} more", hidden=hidden, parent=own_row
                )
            )

    def _process_row(self, node: _Node, parent_row: int | None) -> TreeRow:
        process = _process_of(node)
        return TreeRow(
            depth=node.depth,
            label=f"{_short(process.name)} ({process.pid})",
            pid=process.pid,
            severity=process.max_severity if process.detection_count else None,
            detections=process.detection_count,
            injects=tuple(process.injected_into),
            injection_target=process.pid in self._targets,
            sample=process.pid == self._sample_pid,
            parent=parent_row,
        )


def _short(name: str | None) -> str:
    shown = name or "unknown"
    return shown if len(shown) <= MAX_NAME_CHARS else shown[: MAX_NAME_CHARS - 1] + "…"


@dataclass(frozen=True)
class _Badge:
    text: str
    colour: str
    width: float


@dataclass(frozen=True)
class _Placed:
    row: TreeRow
    x: float
    y: float
    box_width: float
    badges: tuple[_Badge, ...]
    border: str

    @property
    def right(self) -> float:
        badges = sum(badge.width + BADGE_GAP for badge in self.badges)
        return self.x + self.box_width + (BADGE_GAP + badges if self.badges else 0)


class TreeDrawing:
    """The rows as SVG text: `svg()` whole, `windows()` cut between rows."""

    def __init__(self, rows: Sequence[TreeRow], palette: TreePalette) -> None:
        self._rows = tuple(rows)
        self._palette = palette
        self._placed = [self._place(index, row) for index, row in enumerate(self._rows)]
        self._width = max((placed.right for placed in self._placed), default=0) + PAD
        self._height = _bottom_of(len(self._rows))

    def svg(self) -> str:
        return self._draw(0, len(self._rows))

    def windows(self, rows_per_window: int = ROWS_PER_WINDOW) -> list[str]:
        """The tree in pieces of `rows_per_window` rows, each cut in the gap between two rows so no
        box is split. Every piece is as wide as the whole tree, so text scales alike across pages.
        """
        if rows_per_window < 1:
            raise ValueError("rows_per_window must be at least 1")
        starts = range(0, len(self._rows), rows_per_window) or range(1)
        return [self._draw(start, start + rows_per_window) for start in starts]

    def _place(self, index: int, row: TreeRow) -> _Placed:
        palette = self._palette
        badges = tuple(_badges(row, palette))
        border = SEVERITY_COLOURS[row.severity] if row.severity else palette.border
        if row.injection_target:
            border = INJECTION_COLOUR
        return _Placed(
            row=row,
            x=PAD + row.depth * INDENT,
            y=_top_of(index),
            box_width=len(row.label) * CHAR_WIDTH + LABEL_PADDING,
            badges=badges,
            border=border,
        )

    def _draw(self, first: int, stop: int) -> str:
        last = min(stop, len(self._rows))
        top = 0.0 if first == 0 else _cut_above(first)
        bottom = self._height if last == len(self._rows) else _cut_above(last)
        root = ET.Element(
            "svg",
            {
                "xmlns": "http://www.w3.org/2000/svg",
                "viewBox": f"0 0 {self._width:.0f} {bottom - top:.0f}",
                "width": f"{self._width:.0f}",
                "height": f"{bottom - top:.0f}",
                "role": "img",
                "font-family": MONO_FONTS,
            },
        )
        ET.SubElement(root, "title").text = "Process tree"
        ET.SubElement(
            root,
            "rect",
            {"width": "100%", "height": "100%", "fill": self._palette.background},
        )
        window = self._placed[first:last]
        for placed in window:
            self._connector(root, placed, top)
        for placed in window:
            self._box(root, placed, top)
        return ET.tostring(root, encoding="unicode")

    def _connector(self, root: ET.Element, placed: _Placed, top: float) -> None:
        if placed.row.parent is None:
            return
        parent = self._placed[placed.row.parent]
        parent_x = parent.x + CONNECTOR_OFFSET
        start = max(parent.y + BOX_HEIGHT - top, 0.0)
        end = placed.y + BOX_HEIGHT / 2 - top
        ET.SubElement(
            root,
            "path",
            {
                "d": f"M{parent_x:.1f} {start:.1f} V{end:.1f} H{placed.x:.1f}",
                "fill": "none",
                "stroke": self._palette.connector,
                "stroke-width": "1.5",
            },
        )

    def _box(self, root: ET.Element, placed: _Placed, top: float) -> None:
        row, y = placed.row, placed.y - top
        if row.pid is None:
            self._text(root, (placed.x + 8, y + 15), row.label, self._palette.muted).set(
                "font-style", "italic"
            )
            return
        attributes = {
            "x": f"{placed.x:.1f}",
            "y": f"{y:.1f}",
            "width": f"{placed.box_width:.1f}",
            "height": str(BOX_HEIGHT),
            "fill": self._palette.box_fill,
            "stroke": placed.border,
            "stroke-width": "2",
        }
        if row.injection_target:
            attributes["stroke-dasharray"] = "5 3"
        ET.SubElement(root, "rect", attributes)
        self._text(root, (placed.x + 8, y + 15), row.label, self._palette.ink)
        cursor = placed.x + placed.box_width + BADGE_GAP
        for badge in placed.badges:
            self._badge(root, badge, cursor, y)
            cursor += badge.width + BADGE_GAP

    def _badge(self, root: ET.Element, badge: _Badge, x: float, y: float) -> None:
        ET.SubElement(
            root,
            "rect",
            {
                "x": f"{x:.1f}",
                "y": f"{y + 2:.1f}",
                "width": f"{badge.width:.1f}",
                "height": str(BOX_HEIGHT - 4),
                "fill": self._palette.box_fill,
                "stroke": badge.colour,
                "stroke-width": "1.5",
            },
        )
        text = self._text(
            root, (x + BADGE_PADDING / 2, y + 15), badge.text, self._palette.ink, BADGE_SIZE
        )
        text.set("font-weight", "bold")

    @staticmethod
    def _text(
        root: ET.Element, at: tuple[float, float], content: str, fill: str, size: int = LABEL_SIZE
    ) -> ET.Element:
        element = ET.SubElement(
            root,
            "text",
            {"x": f"{at[0]:.1f}", "y": f"{at[1]:.1f}", "fill": fill, "font-size": str(size)},
        )
        element.text = content
        return element


def _top_of(index: int) -> float:
    return PAD + index * ROW_HEIGHT


def _bottom_of(row_count: int) -> float:
    if row_count == 0:
        return 2 * PAD
    return _top_of(row_count - 1) + BOX_HEIGHT + PAD


def _cut_above(index: int) -> float:
    return _top_of(index) - (ROW_HEIGHT - BOX_HEIGHT) / 2


def _badges(row: TreeRow, palette: TreePalette) -> list[_Badge]:
    texts: list[tuple[str, str]] = []
    if row.sample:
        texts.append(("SAMPLE", palette.border))
    if row.severity:
        texts.append((f"{row.severity.upper()} {row.detections}", SEVERITY_COLOURS[row.severity]))
    if row.injects:
        listed = ",".join(str(pid) for pid in row.injects[:MAX_LISTED_TARGETS])
        more = "…" if len(row.injects) > MAX_LISTED_TARGETS else ""
        texts.append((f"INJECTS {listed}{more}", INJECTION_COLOUR))
    if row.injection_target:
        texts.append(("INJECTION TARGET", INJECTION_COLOUR))
    return [
        _Badge(text, colour, len(text) * BADGE_CHAR_WIDTH + BADGE_PADDING) for text, colour in texts
    ]
