"""Helpers for tests that look inside a rendered report."""

from html.parser import HTMLParser

from app.export.inputs import ExportAnnotations, ExportNote, TargetType
from app.export.report.assemble import build_report_model
from app.export.report.model import ReportInclude, ReportModel
from app.schemas.views_events import ProcessTree
from app.schemas.views_findings import IocsView, IocType
from tests.export.conftest import make_ioc
from tests.export.report.fixtures import facts, make_inputs, process

SCRIPT = "<script>alert(1)</script>"
BREAKOUT = '"><img src=x onerror=alert(2)>'


class Page(HTMLParser):
    """The tags, attributes, ids and visible text of an HTML document."""

    def __init__(self, html: str) -> None:
        super().__init__()
        self.tags: list[str] = []
        self.attributes: list[tuple[str, str, str | None]] = []
        self.ids: list[str] = []
        self._text: list[str] = []
        self.feed(html)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.tags.append(tag)
        for name, value in attrs:
            self.attributes.append((tag, name, value))
            if name == "id" and value:
                self.ids.append(value)

    def handle_data(self, data: str) -> None:
        self._text.append(data)

    @property
    def text(self) -> str:
        return " ".join(" ".join(self._text).split())


def hostile_model(include: ReportInclude | None = None) -> ReportModel:
    """Every string an attacker or a careless analyst could control, set to markup."""
    inputs = make_inputs()
    hostile_tree = ProcessTree(
        roots=[
            process(4242, f"{SCRIPT}{BREAKOUT}", detection_count=1),
            process(5, "plain.exe"),
        ],
        total=2,
    )
    detections = inputs.detections.model_copy(deep=True)
    detections.groups[0].detections[0].name = f"{SCRIPT} detection"
    detections.groups[0].detections[0].description = BREAKOUT
    detections.groups[0].detections[0].author = f"{SCRIPT}{BREAKOUT}"
    notes = (
        ExportNote(f"note {SCRIPT} {BREAKOUT}", TargetType.ANALYSIS, None),
        ExportNote(BREAKOUT, TargetType.PROCESS, "4242"),
        ExportNote(SCRIPT, TargetType.EVENT, "ev-dns"),
    )
    changed = ExportAnnotations(tags=(f"{SCRIPT}", BREAKOUT), notes=notes)
    iocs = IocsView(
        iocs=[make_ioc(IocType.URL, f"http://evil.example/{SCRIPT}{BREAKOUT}", BREAKOUT)],
        truncated_types=[],
    )
    analysis = inputs.analysis
    analysis.filename = f"{SCRIPT}{BREAKOUT}.exe"
    hostile_inputs = make_inputs(
        analysis=analysis,
        tree=hostile_tree,
        detections=detections,
        annotations=changed,
        iocs=iocs,
        process_events=[facts("proc-1", 3, "process", f"{SCRIPT}{BREAKOUT}")],
        note_events={"ev-dns": facts("ev-dns", 10, "network", f"{BREAKOUT}{SCRIPT}")},
    )
    return build_report_model(hostile_inputs, include or ReportInclude())
