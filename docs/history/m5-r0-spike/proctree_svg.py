"""Throwaway R0 spike: a static, indented process tree as SVG, plain ElementTree, no browser."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass, field

CHAR_W = 7.2  # a monospace advance is 0.6 em; 12 px type
ROW_H = 28
INDENT = 26
PAD = 12
BOX_H = 22
MAX_NAME = 34
DEFAULT_CAP = 120
MAX_DEPTH = 12

SEVERITY_COLOUR = {
    "critical": "#ef4444",
    "high": "#f97316",
    "medium": "#eab308",
    "low": "#94a3b8",
    "info": "#a3a3a3",
    "informational": "#a3a3a3",
}
SEVERITY_RANK = {"info": 0, "informational": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}
MONO = "'Liberation Mono', 'Courier New', Courier, monospace"
LINE = "#0369a1"
BORDER = "#38bdf8"
INK = "#111827"
INJECT = "#f97316"


@dataclass
class Row:
    depth: int
    label: str
    pid: int | None
    severity: str | None = None
    detections: int = 0
    injects: list[int] = field(default_factory=list)
    injected: bool = False
    sample: bool = False
    hidden: int = 0
    parent: int | None = None  # index of the parent row


def truncate(name: str, limit: int = MAX_NAME) -> str:
    return name if len(name) <= limit else name[: limit - 1] + "…"


def _flag(node: dict) -> bool:
    return bool(node["detection_count"] or node["injected_into"])


def _descendants(node: dict) -> int:
    return sum(1 + _descendants(c) for c in node["children"])


def _select(roots: list[dict], cap: int) -> set[int]:
    """Node ids to keep: flagged nodes with their ancestors first, then breadth-first, up to cap."""
    flat: list[tuple[dict, tuple[int, ...]]] = []
    queue = [(r, ()) for r in roots]
    while queue:
        node, path = queue.pop(0)
        flat.append((node, path))
        queue.extend((c, (*path, id(node))) for c in node["children"])
    keep: set[int] = set()
    for node, path in flat:
        if len(keep) >= cap:
            break
        if _flag(node):
            keep.update(path)
            keep.add(id(node))
    for node, path in flat:
        if len(keep) >= cap:
            break
        keep.update(path)
        keep.add(id(node))
    return keep


def build_rows(roots: list[dict], sample_pid: int | None, cap: int) -> list[Row]:
    total = sum(1 + _descendants(r) for r in roots)
    keep = _select(roots, cap) if total > cap else None
    injected = {pid for r in _walk(roots) for pid in r["injected_into"]}
    rows: list[Row] = []

    def add(node: dict, depth: int, parent: int | None) -> None:
        index = len(rows)
        rows.append(
            Row(
                depth=depth,
                label=f"{truncate(node['name'])} ({node['pid']})",
                pid=node["pid"],
                severity=node["max_severity"] if node["detection_count"] else None,
                detections=node["detection_count"],
                injects=list(node["injected_into"]),
                injected=node["pid"] in injected,
                sample=node["pid"] == sample_pid,
                parent=parent,
            )
        )
        shown = [c for c in node["children"] if (keep is None or id(c) in keep) and depth < MAX_DEPTH]
        for child in shown:
            add(child, depth + 1, index)
        hidden = sum(1 + _descendants(c) for c in node["children"] if not any(c is s for s in shown))
        if hidden:
            rows.append(Row(depth=depth + 1, label=f"+{hidden} more", pid=None, hidden=hidden, parent=index))

    shown_roots = [r for r in roots if keep is None or id(r) in keep]
    for root in shown_roots:
        add(root, 0, None)
    hidden_roots = sum(1 + _descendants(r) for r in roots if not any(r is s for s in shown_roots))
    if hidden_roots:
        rows.append(Row(depth=0, label=f"+{hidden_roots} more", pid=None, hidden=hidden_roots))
    return rows


def _walk(nodes: list[dict]):
    for n in nodes:
        yield n
        yield from _walk(n["children"])


def _badge_text(row: Row) -> str | None:
    if row.severity is None:
        return None
    return f"{row.severity.upper()} {row.detections}"


def _text(parent: ET.Element, x: float, y: float, content: str, size: int = 12, **attrs: str) -> None:
    el = ET.SubElement(parent, "text", x=f"{x:.1f}", y=f"{y:.1f}", **{"font-size": str(size)}, **attrs)
    el.text = content


def render_svg(roots: list[dict], sample_pid: int | None = None, cap: int = DEFAULT_CAP) -> str:
    rows = build_rows(roots, sample_pid, cap)
    layout = []
    max_right = 0.0
    for i, row in enumerate(rows):
        x = PAD + row.depth * INDENT
        y = PAD + i * ROW_H
        width = len(row.label) * CHAR_W + 16
        extras = []
        if row.sample:
            extras.append("SAMPLE")
        badge = _badge_text(row)
        if badge:
            extras.append(badge)
        if row.injects:
            extras.append("INJECTS " + ",".join(str(p) for p in row.injects[:3]) + ("…" if len(row.injects) > 3 else ""))
        if row.injected:
            extras.append("INJECTION TARGET")
        extra_w = sum(len(e) * 6.6 + 14 for e in extras)
        layout.append((row, x, y, width, extras))
        max_right = max(max_right, x + width + extra_w)
    width = max_right + PAD
    height = PAD * 2 + len(rows) * ROW_H - (ROW_H - BOX_H)

    svg = ET.Element(
        "svg",
        xmlns="http://www.w3.org/2000/svg",
        viewBox=f"0 0 {width:.0f} {height:.0f}",
        width=f"{width:.0f}",
        height=f"{height:.0f}",
        role="img",
        **{"font-family": MONO},
    )
    ET.SubElement(svg, "title").text = "Process tree"
    ET.SubElement(svg, "rect", width="100%", height="100%", fill="#ffffff")

    mid = {i: y + BOX_H / 2 for i, (_, _, y, _, _) in enumerate(layout)}
    for i, (row, x, y, _, _) in enumerate(layout):
        if row.parent is None:
            continue
        px = PAD + rows[row.parent].depth * INDENT + 10
        ET.SubElement(svg, "path", d=f"M{px:.1f} {mid[row.parent] + BOX_H / 2:.1f} V{mid[i]:.1f} H{x:.1f}",
                      fill="none", stroke=LINE, **{"stroke-width": "1.5"})

    for row, x, y, w, extras in layout:
        if row.pid is None:
            _text(svg, x + 8, y + 15, row.label, fill="#6b7280", **{"font-style": "italic"})
            continue
        stroke = SEVERITY_COLOUR[row.severity] if row.severity else BORDER
        box = {"x": f"{x:.1f}", "y": f"{y:.1f}", "width": f"{w:.1f}", "height": str(BOX_H),
               "fill": "#ffffff", "stroke": stroke, "stroke-width": "2"}
        if row.injected:
            box.update({"stroke": INJECT, "stroke-dasharray": "5 3"})
        ET.SubElement(svg, "rect", **box)
        _text(svg, x + 8, y + 15, row.label, fill=INK)
        cursor = x + w + 8
        for extra in extras:
            tw = len(extra) * 6.6 + 12
            colour = INJECT if extra.startswith("INJECT") else (stroke if extra.split()[0].lower() in SEVERITY_COLOUR else LINE)
            ET.SubElement(svg, "rect", x=f"{cursor:.1f}", y=f"{y + 2:.1f}", width=f"{tw:.1f}", height=str(BOX_H - 4),
                          fill="#ffffff", stroke=colour, **{"stroke-width": "1.5"})
            _text(svg, cursor + 6, y + 15, extra, size=10, fill=INK, **{"font-weight": "bold"})
            cursor += tw + 6
    return ET.tostring(svg, encoding="unicode")


def tree_from_view(view: dict) -> list[dict]:
    return view["roots"]
