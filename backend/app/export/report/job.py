import asyncio
import contextlib
import os
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.analysis_repository import get_analysis
from app.export.report.gather import ReportSources, gather_report
from app.export.report.model import ReportModel
from app.export.report.render import ReportVariant, render_html, render_pdf
from app.export.report.request import ReportNotPossibleError, ReportRequest, reason_not_reportable
from app.jobs.exports import file_result
from app.jobs.runner import AsyncJobHandler, JobContext, JobResult
from app.search.index import EventIndex
from app.views.attack_table import AttackTable

MEDIA_TYPES = {
    ReportVariant.HTML: "text/html; charset=utf-8",
    ReportVariant.PDF: "application/pdf",
}
GATHER_SHARE_PERCENT = 90
RENDER_START_PERCENT = 90
SAVE_START_PERCENT = 99
RENDER_STEPS = {
    ReportVariant.HTML: "Rendering the page",
    ReportVariant.PDF: "Rendering the PDF",
}


def export_report_handler(
    session_factory: async_sessionmaker[AsyncSession],
    index: EventIndex,
    storage_root: Path,
    attack_table: AttackTable,
) -> AsyncJobHandler:
    async def export_report(context: JobContext) -> JobResult:
        request = ReportRequest.model_validate(context.params)
        if context.analysis_id is None:
            raise ReportNotPossibleError(
                "A report job needs an analysis, and this one has no analysis"
            )
        sources = _Sources(session_factory, index, storage_root, attack_table)
        model = await _gather(context, context.analysis_id, request, sources)
        context.report_progress(RENDER_STEPS[request.format], RENDER_START_PERCENT)
        content = await asyncio.to_thread(_render, model, request.format)
        context.report_progress("Saving the file", SAVE_START_PERCENT)
        filename = f"tartarus-report-{context.analysis_id}.{request.format.value}"
        # Each job keeps its own file: the download of an earlier job must not serve a later report.
        produced = context.analysis_dir() / f"job-{context.job_id}-{filename}"
        await asyncio.to_thread(_save_whole, produced, content, context.job_id)
        return file_result(context.exports_dir, produced, filename, MEDIA_TYPES[request.format])

    return export_report


@dataclass(frozen=True)
class _Sources:
    session_factory: async_sessionmaker[AsyncSession]
    index: EventIndex
    storage_root: Path
    attack_table: AttackTable


async def _gather(
    context: JobContext, analysis_id: int, request: ReportRequest, sources: _Sources
) -> ReportModel:
    # The session lives only as long as the gathering: the render that follows can take seconds.
    async with sources.session_factory() as session:
        analysis = await get_analysis(session, analysis_id)
        if analysis is None:
            raise ReportNotPossibleError(f"Analysis {analysis_id} no longer exists")
        if reason := reason_not_reportable(analysis):
            raise ReportNotPossibleError(reason)
        return await gather_report(
            analysis,
            ReportSources(session, sources.index, sources.storage_root, sources.attack_table),
            request.include,
            lambda step, percent: context.report_progress(
                step, percent * GATHER_SHARE_PERCENT // 100
            ),
        )


def _render(model: ReportModel, variant: ReportVariant) -> bytes:
    if variant is ReportVariant.PDF:
        return render_pdf(model)
    return render_html(model).encode("utf-8")


def _save_whole(destination: Path, content: bytes, job_id: int) -> None:
    """Blocking. The file is complete under its own name or not there: a download that races
    the rename sees the earlier report, never half of this one."""
    partial = destination.with_name(f"{destination.name}.{job_id}.part")
    try:
        partial.write_bytes(content)
        os.replace(partial, destination)
    finally:
        with contextlib.suppress(FileNotFoundError):
            partial.unlink()
