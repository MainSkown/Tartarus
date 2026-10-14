import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db import analysis_repository
from app.db.models import Analysis
from app.db.models.analysis import AnalysisStatus
from app.export.report import job
from app.export.report.assemble import build_report_model
from app.export.report.gather import ProgressCallback, ReportSources
from app.export.report.model import ReportInclude, ReportModel
from app.export.report.request import ReportNotPossibleError
from app.jobs.exports import resolve_export
from app.jobs.runner import AsyncJobHandler, JobContext
from app.views.attack_table import load_attack_table
from tests.export.report.fixtures import SAMPLE_NAME, make_inputs
from tests.test_analysis_repository import seeded_analysis

FAKE_PDF = b"%PDF-1.7 fake report"
GATHER_STEPS = (("Reading the analysis files", 5), ("Assembling the report", 95))


@dataclass
class Rig:
    """The handler under test with its views and renderers replaced, and what they saw."""

    factory: async_sessionmaker[AsyncSession]
    exports: Path
    analysis: Analysis
    progress: list[tuple[str, int]] = field(default_factory=list)
    gathered_with: list[tuple[ReportSources, ReportInclude]] = field(default_factory=list)
    rendered: list[str] = field(default_factory=list)

    def context(
        self, params: dict[str, Any], analysis_id: int | None = None, job_id: int = 11
    ) -> JobContext:
        return JobContext(
            job_id=job_id,
            analysis_id=self.analysis.id if analysis_id is None else analysis_id,
            params=params,
            exports_dir=self.exports,
            report_progress=lambda step, percent: self.progress.append((step, percent)),
        )

    def handler(self) -> AsyncJobHandler:
        return job.export_report_handler(
            self.factory,
            index=object(),  # type: ignore[arg-type]
            storage_root=Path("/cape"),
            attack_table=ATTACK_TABLE,
        )

    async def run(self, format_: str = "pdf", job_id: int = 11, **include: bool) -> dict[str, Any]:
        params = {"format": format_, "include": include}
        return await self.handler()(self.context(params, job_id=job_id))

    @property
    def files(self) -> list[str]:
        directory = self.exports / str(self.analysis.id)
        return sorted(path.name for path in directory.iterdir()) if directory.exists() else []


ATTACK_TABLE = load_attack_table()


@pytest.fixture
async def rig(
    session_factory: async_sessionmaker[AsyncSession],
    session: AsyncSession,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Rig:
    analysis = await seeded_analysis(session, filename=SAMPLE_NAME)
    await analysis_repository.update_analysis(session, analysis.id, status=AnalysisStatus.DONE)
    rig = Rig(session_factory, tmp_path / "exports", analysis)

    async def gather(
        found: Analysis,
        sources: ReportSources,
        include: ReportInclude,
        progress: ProgressCallback,
    ) -> ReportModel:
        rig.gathered_with.append((sources, include))
        for step, percent in GATHER_STEPS:
            progress(step, percent)
        return build_report_model(make_inputs(), include)

    def render_pdf(model: ReportModel) -> bytes:
        rig.rendered.append("pdf")
        return FAKE_PDF

    monkeypatch.setattr(job, "gather_report", gather)
    monkeypatch.setattr(job, "render_pdf", render_pdf)
    return rig


async def test_a_pdf_report_is_saved_under_the_analysis_and_described_for_download(
    rig: Rig,
) -> None:
    result = await rig.run("pdf")

    name = f"tartarus-report-{rig.analysis.id}.pdf"
    assert result == {
        "file": f"{rig.analysis.id}/job-11-{name}",
        "filename": name,
        "media_type": "application/pdf",
    }
    produced = resolve_export(rig.exports, result["file"])
    assert produced is not None
    assert produced.read_bytes() == FAKE_PDF


async def test_an_html_report_is_the_rendered_page_as_utf8(rig: Rig) -> None:
    result = await rig.run("html")

    assert result["media_type"] == "text/html; charset=utf-8"
    assert result["filename"] == f"tartarus-report-{rig.analysis.id}.html"
    produced = resolve_export(rig.exports, result["file"])
    assert produced is not None
    page = produced.read_text(encoding="utf-8")
    assert page.lower().startswith("<!doctype html>")
    assert SAMPLE_NAME in page
    assert rig.rendered == []


async def test_the_report_is_gathered_for_the_analysis_with_the_include_options(rig: Rig) -> None:
    await rig.run("pdf", notes=False, screenshots=True)

    [(sources, include)] = rig.gathered_with
    assert include == ReportInclude(notes=False, screenshots=True, raw_iocs=True)
    assert sources.storage_root == Path("/cape")
    assert sources.attack_table is ATTACK_TABLE


async def test_progress_rises_through_named_steps_and_stays_below_one_hundred(rig: Rig) -> None:
    await rig.run("pdf")

    percents = [percent for _step, percent in rig.progress]
    assert percents == sorted(percents)
    assert len(set(percents)) == len(percents)
    assert rig.progress[0] == ("Reading the analysis files", 4)
    assert percents[-1] == 99
    assert max(percents[:-2]) < 90
    assert [step for step, _ in rig.progress][-3:] == [
        "Assembling the report",
        "Rendering the PDF",
        "Saving the file",
    ]


async def test_the_html_variant_says_it_renders_a_page(rig: Rig) -> None:
    await rig.run("html")

    assert "Rendering the page" in [step for step, _ in rig.progress]


async def test_the_file_appears_whole_or_not_at_all(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen_while_writing: list[list[str]] = []
    replace = os.replace

    def watching_replace(source: Any, destination: Any) -> None:
        seen_while_writing.append(rig.files)
        replace(source, destination)

    monkeypatch.setattr(job.os, "replace", watching_replace)

    await rig.run("pdf")

    [before_rename] = seen_while_writing
    assert [name.endswith(".part") for name in before_rename] == [True]
    assert rig.files == [f"job-11-tartarus-report-{rig.analysis.id}.pdf"]


async def test_a_failed_save_leaves_no_temporary_file_and_keeps_the_earlier_report(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    await rig.run("pdf")
    earlier = rig.files

    def refuse(_source: Any, _destination: Any) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(job.os, "replace", refuse)

    with pytest.raises(OSError, match="disk full"):
        await rig.run("pdf")

    assert rig.files == earlier


async def test_a_render_that_fails_says_why_and_leaves_nothing_behind(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(_model: ReportModel) -> bytes:
        raise RuntimeError("Pango is missing")

    monkeypatch.setattr(job, "render_pdf", broken)

    with pytest.raises(RuntimeError, match="Pango is missing"):
        await rig.run("pdf")

    assert rig.files == []


async def test_a_second_report_leaves_the_first_jobs_file_as_it_was(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = await rig.run("pdf", job_id=11)
    monkeypatch.setattr(job, "render_pdf", lambda _model: b"%PDF-1.7 second")

    second = await rig.run("pdf", job_id=12)

    assert first["file"] != second["file"]
    assert second["filename"] == first["filename"]
    first_file = resolve_export(rig.exports, first["file"])
    second_file = resolve_export(rig.exports, second["file"])
    assert first_file is not None
    assert second_file is not None
    assert first_file.read_bytes() == FAKE_PDF
    assert second_file.read_bytes() == b"%PDF-1.7 second"


async def test_the_pdf_and_the_html_report_of_one_analysis_live_side_by_side(rig: Rig) -> None:
    await rig.run("pdf")
    await rig.run("html")

    assert rig.files == [
        f"job-11-tartarus-report-{rig.analysis.id}.html",
        f"job-11-tartarus-report-{rig.analysis.id}.pdf",
    ]


@pytest.mark.parametrize(
    "status",
    [
        AnalysisStatus.QUEUED,
        AnalysisStatus.RUNNING,
        AnalysisStatus.INGESTING,
        AnalysisStatus.FAILED,
        AnalysisStatus.REPORT_FAILED,
        AnalysisStatus.CANCELLED,
    ],
)
async def test_an_analysis_that_is_not_done_gets_no_report(
    rig: Rig, session: AsyncSession, status: AnalysisStatus
) -> None:
    await analysis_repository.update_analysis(session, rig.analysis.id, status=status)

    with pytest.raises(ReportNotPossibleError, match=f"finished analyses.*{status.value}"):
        await rig.run("pdf")

    assert rig.gathered_with == []
    assert rig.files == []


async def test_an_analysis_that_is_gone_gets_no_report(rig: Rig) -> None:
    with pytest.raises(ReportNotPossibleError, match="999 no longer exists"):
        await rig.handler()(rig.context({"format": "pdf", "include": {}}, analysis_id=999))


async def test_a_job_without_an_analysis_is_refused(rig: Rig) -> None:
    context = JobContext(11, None, {"format": "pdf"}, rig.exports, lambda *_: None)

    with pytest.raises(ReportNotPossibleError, match="no analysis"):
        await rig.handler()(context)


async def test_the_session_is_closed_before_the_render_starts(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    held: list[bool] = []

    def render_pdf(_model: ReportModel) -> bytes:
        [(sources, _include)] = rig.gathered_with
        held.append(sources.session.in_transaction())
        return FAKE_PDF

    monkeypatch.setattr(job, "render_pdf", render_pdf)

    await rig.run("pdf")

    assert held == [False]
