import io

import pypdf
import pytest

from app.annotations.validation import Target
from app.db import analysis_repository as repository
from app.db import annotation_repository
from app.db.models.annotation import TargetType
from app.export.report.gather import ReportSources, gather_report
from app.export.report.key_events import MAX_KEY_EVENTS, KeyEventReason
from app.export.report.model import ReportInclude
from app.export.report.render import render_html, render_pdf
from app.views.attack_table import load_attack_table
from tests.integration.views.conftest import ViewStack
from tests.integration.views.findings.support import install_report

pytestmark = pytest.mark.integration


async def gather_from(stack: ViewStack, include: ReportInclude | None = None):
    async with stack.factory() as session:
        analysis = await repository.get_analysis(session, stack.analysis_id)
        assert analysis is not None
        sources = ReportSources(session, stack.index, stack.storage_root, load_attack_table())
        return await gather_report(analysis, sources, include or ReportInclude())


async def test_the_report_of_a_real_ingest_has_every_section_filled(stack: ViewStack) -> None:
    install_report(stack)

    model = await gather_from(stack)

    assert model.header.sample_name == "benign.exe"
    assert model.process_tree
    assert model.detections
    assert model.network.dns.total > 0
    assert model.iocs
    reasons = {event.reason for event in model.key_events.events}
    assert KeyEventReason.ALERT in reasons
    assert 0 < len(model.key_events.events) <= MAX_KEY_EVENTS
    times = [event.time for event in model.key_events.events]
    assert times == sorted(times)


async def test_the_analysts_note_on_a_real_process_and_event_reaches_the_report(
    stack: ViewStack,
) -> None:
    install_report(stack)
    first = await gather_from(stack)
    process_pid = str(next(row.pid for row in first.process_tree if row.pid is not None))
    event_id = first.key_events.events[0].id
    async with stack.factory() as session:
        for target, body in [
            (Target(TargetType.ANALYSIS), "Analyst verdict: benign."),
            (Target(TargetType.PROCESS, process_pid), "Process note."),
            (Target(TargetType.EVENT, event_id), "Event note."),
        ]:
            await annotation_repository.add_note(session, stack.analysis_id, target, body)

    model = await gather_from(stack)
    html = render_html(model)

    assert {group.target_type.value for group in model.notes} == {"analysis", "process", "event"}
    assert "Analyst verdict: benign." in html


async def test_a_real_report_renders_to_html_and_to_a_pdf_with_its_text(stack: ViewStack) -> None:
    install_report(stack)
    model = await gather_from(stack, ReportInclude(screenshots=False))

    pdf = render_pdf(model)

    assert "benign.exe" in render_html(model)
    text = " ".join(page.extract_text() for page in pypdf.PdfReader(io.BytesIO(pdf)).pages)
    assert "benign.exe" in text
