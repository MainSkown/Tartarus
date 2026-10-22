import asyncio
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.background import BackgroundTask

from app.api.dependencies import get_cape_storage_path, get_event_index, require_analysis
from app.db.models import Analysis
from app.db.session import get_session
from app.schemas.views_findings import (
    ArtifactsView,
    AttackMatrix,
    DetectionsView,
    IocsView,
)
from app.search.index import EventIndex
from app.views.artifacts import (
    SCREENSHOT_MEDIA_TYPES,
    AnalysisFiles,
    TemporarySpaceError,
    download_name,
    pack_for_download,
    read_analysis_files,
)
from app.views.attack import attack_matrix
from app.views.attack_table import AttackTable, load_attack_table
from app.views.detections import list_detections
from app.views.iocs import collect_iocs

PCAP_MEDIA_TYPE = "application/vnd.tcpdump.pcap"
ZIP_MEDIA_TYPE = "application/zip"

router = APIRouter(prefix="/analyses", tags=["views"])


async def existing_analysis(
    analysis_id: int, session: Annotated[AsyncSession, Depends(get_session)]
) -> Analysis:
    return await require_analysis(session, analysis_id)


async def analysis_files(
    analysis: Annotated[Analysis, Depends(existing_analysis)],
    storage: Annotated[Path, Depends(get_cape_storage_path)],
) -> AnalysisFiles:
    return await asyncio.to_thread(read_analysis_files, storage, analysis.cape_task_id)


ExistingAnalysis = Annotated[Analysis, Depends(existing_analysis)]
Index = Annotated[EventIndex, Depends(get_event_index)]
Files = Annotated[AnalysisFiles, Depends(analysis_files)]


@router.get("/{analysis_id}/detections")
async def detections(analysis: ExistingAnalysis, index: Index) -> DetectionsView:
    """Every detection of the analysis grouped by ruleset (Sigma, CAPE, YARA, Suricata, then
    any other), most severe first and by name within a severity. Each detection lists up to 50 of
    the events that triggered it and the total.
    """
    return await list_detections(index, analysis.id)


@router.get("/{analysis_id}/attack")
async def attack(
    analysis: ExistingAnalysis,
    index: Index,
    table: Annotated[AttackTable, Depends(load_attack_table)],
) -> AttackMatrix:
    """The ATT&CK techniques the detections raised, by tactic in kill-chain order. A technique of
    several tactics appears under each; one the bundled ATT&CK table does not know goes under the
    tactic `unknown` with no name. Tactics without a hit are left out.
    """
    return await attack_matrix(index, analysis.id, table)


@router.get("/{analysis_id}/iocs")
async def iocs(analysis: ExistingAnalysis, index: Index, files: Files) -> IocsView:
    """Deduplicated indicators from the events and the report: hashes, domains, IPs (not the
    sandbox network), URLs, mutexes, registry paths and file paths. `truncated_types` lists
    types that had more distinct values than are returned.
    """
    return await collect_iocs(index, analysis, files)


@router.get("/{analysis_id}/artifacts")
async def artifacts(files: Files) -> ArtifactsView:
    """What the run produced, computed from CAPE's `report.json` and the analysis folder. An
    analysis without a readable report lists nothing.
    """
    return files.catalog.view


@router.get(
    "/{analysis_id}/artifacts/{artifact_id}/download",
    response_class=FileResponse,
    responses={200: {"content": {ZIP_MEDIA_TYPE: {}}}},
)
async def download_artifact(artifact_id: str, files: Files) -> FileResponse:
    """The artifact as an AES-encrypted zip, password `infected`. `404` for an id the artifact
    list does not hold or whose file is gone; `507` when the temporary directory has less free
    space than the file.
    """
    file = files.catalog.files.get(artifact_id)
    if file is None:
        raise HTTPException(404, "Artifact not found")
    try:
        packed = await pack_for_download(file)
    except TemporarySpaceError:
        raise HTTPException(507, "Not enough temporary disk space to pack this artifact") from None
    return FileResponse(
        packed,
        media_type=ZIP_MEDIA_TYPE,
        filename=f"{download_name(file.name)}.zip",
        background=BackgroundTask(packed.unlink, missing_ok=True),
    )


@router.get(
    "/{analysis_id}/artifacts/screenshots/{n}",
    response_class=FileResponse,
    responses={200: {"content": {"image/png": {}, "image/jpeg": {}}}},
)
async def screenshot(n: int, files: Files) -> FileResponse:
    """Screenshot `n`, counted from 1 as in the artifact list, as the raw image."""
    shots = files.catalog.screenshots
    if not 1 <= n <= len(shots):
        raise HTTPException(404, f"Screenshot {n} not found")
    path = shots[n - 1]
    return FileResponse(path, media_type=SCREENSHOT_MEDIA_TYPES[path.suffix.lower()])


@router.get(
    "/{analysis_id}/pcap",
    response_class=FileResponse,
    responses={200: {"content": {PCAP_MEDIA_TYPE: {}}}},
)
async def pcap(analysis: ExistingAnalysis, files: Files) -> FileResponse:
    """The guest's network capture, raw."""
    path = files.catalog.pcap
    if path is None:
        raise HTTPException(404, "This analysis has no network capture")
    return FileResponse(path, media_type=PCAP_MEDIA_TYPE, filename=f"analysis-{analysis.id}.pcap")
