from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.annotations.read import load_annotations
from app.api.dependencies import get_job_runner
from app.api.views_findings import ExistingAnalysis, Files, Index
from app.db.models import Sample
from app.db.models.job import JobType
from app.db.session import get_session
from app.export.assembly import build_export_input, export_annotations
from app.export.formats import ExportFormat, export_filename, render
from app.export.inputs import ExportAnnotations, IocExportInput
from app.export.report.request import ReportRequest, reason_not_reportable
from app.jobs.runner import JobRunner
from app.schemas.jobs import JobRead
from app.schemas.views_findings import IocsView
from app.views.attack_table import AttackTable, load_attack_table
from app.views.iocs import collect_iocs

router = APIRouter(prefix="/analyses", tags=["export"])


async def load_export_annotations(
    analysis: ExistingAnalysis,
    session: Annotated[AsyncSession, Depends(get_session)],
    index: Index,
) -> ExportAnnotations:
    return export_annotations(await load_annotations(session, index, analysis.id))


async def found_iocs(analysis: ExistingAnalysis, index: Index, files: Files) -> IocsView:
    return await collect_iocs(index, analysis, files)


async def submitted_sample(
    analysis: ExistingAnalysis, session: Annotated[AsyncSession, Depends(get_session)]
) -> Sample | None:
    return await session.get(Sample, analysis.sample_sha256)


async def ioc_export_input(
    analysis: ExistingAnalysis,
    found: Annotated[IocsView, Depends(found_iocs)],
    sample: Annotated[Sample | None, Depends(submitted_sample)],
    annotations: Annotated[ExportAnnotations, Depends(load_export_annotations)],
    table: Annotated[AttackTable, Depends(load_attack_table)],
) -> IocExportInput:
    return build_export_input(analysis, sample, found.iocs, annotations, table)


@router.get(
    "/{analysis_id}/export/iocs",
    response_class=Response,
    responses={200: {"content": {export_format.media_type: {} for export_format in ExportFormat}}},
)
async def iocs(
    format_: Annotated[ExportFormat, Query(alias="format")],
    inputs: Annotated[IocExportInput, Depends(ioc_export_input)],
) -> Response:
    """The IOCs of the analysis, the same list the IOCs view shows, as a download: a STIX 2.1
    bundle, a MISP event or a CSV. The analyst's tags and notes and the ATT&CK techniques the
    run raised go in where the format has a place for them. Ids and times derive from the
    analysis, so exporting twice gives the same file.
    """
    filename = export_filename(inputs.analysis_id, format_)
    return Response(
        render(format_, inputs),
        media_type=format_.media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/{analysis_id}/export/report", status_code=202)
async def report(
    analysis: ExistingAnalysis,
    request: ReportRequest,
    runner: Annotated[JobRunner, Depends(get_job_runner)],
) -> JobRead:
    """Starts building the report of a finished analysis as a self-contained HTML page or a PDF,
    and answers `202` with the pending job. Follow the job on `/ws/system` or `GET /jobs/{id}`;
    when it is `done`, `GET /jobs/{id}/download` returns the file. `include` leaves sections out
    (the analyst's notes, the screenshots, the raw IOC lists); all three default to included.
    `404` for an unknown analysis, `409` unless it is `done`, `422` for a format that is neither
    `html` nor `pdf`.
    """
    if reason := reason_not_reportable(analysis):
        raise HTTPException(409, reason)
    job = await runner.submit(JobType.EXPORT_REPORT, analysis.id, request.model_dump(mode="json"))
    return JobRead.model_validate(job)
