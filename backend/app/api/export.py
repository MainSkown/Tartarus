from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.views_findings import ExistingAnalysis, Files, Index
from app.db.models import Sample
from app.db.session import get_session
from app.export.assembly import build_export_input
from app.export.formats import ExportFormat, export_filename, render
from app.export.inputs import ExportAnnotations, IocExportInput
from app.schemas.views_findings import IocsView
from app.views.attack_table import AttackTable, load_attack_table
from app.views.iocs import collect_iocs

router = APIRouter(prefix="/analyses", tags=["export"])


# The seam for the annotations repository: it will need the analysis, so the signature keeps it.
async def load_export_annotations(analysis: ExistingAnalysis) -> ExportAnnotations:  # noqa: ARG001
    """The tags and notes an export carries. The one place to read them from the annotations
    repository; until it is wired here the exports carry none.
    """
    return ExportAnnotations()


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
