import mimetypes
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_exports_path
from app.db.job_repository import get_job
from app.db.models import Job
from app.db.models.job import JobStatus
from app.db.session import get_session
from app.jobs.exports import resolve_export
from app.schemas.jobs import JobRead

router = APIRouter(prefix="/jobs", tags=["jobs"])

DEFAULT_MEDIA_TYPE = "application/octet-stream"


async def require_job(job_id: int, session: Annotated[AsyncSession, Depends(get_session)]) -> Job:
    job = await get_job(session, job_id)
    if job is None:
        raise HTTPException(404, f"Job {job_id} not found")
    return job


ExistingJob = Annotated[Job, Depends(require_job)]


@router.get("/{job_id}")
async def read(job: ExistingJob) -> JobRead:
    """The job's status, step, progress, log tail and result. `404` when unknown."""
    return JobRead.model_validate(job)


@router.get("/{job_id}/download", response_class=FileResponse)
async def download(
    job: ExistingJob, exports: Annotated[Path, Depends(get_exports_path)]
) -> FileResponse:
    """The file a finished job produced, named by the job's result. `404` when the job is
    unknown, produced no file, or the file is gone; `409` unless the job is `done`.
    """
    if job.status is not JobStatus.DONE:
        raise HTTPException(409, f"Job {job.id} is {job.status.value}, not done")
    result = job.result or {}
    file = _produced_file(exports, result)
    if file is None:
        raise HTTPException(404, f"Job {job.id} has no file to download")
    filename = str(result.get("filename") or file.name)
    return FileResponse(file, media_type=_media_type(result, filename), filename=filename)


def _produced_file(exports: Path, result: dict[str, Any]) -> Path | None:
    name = result.get("file")
    return resolve_export(exports, name) if isinstance(name, str) else None


def _media_type(result: dict[str, Any], filename: str) -> str:
    declared = result.get("media_type")
    if isinstance(declared, str):
        return declared
    return mimetypes.guess_type(filename)[0] or DEFAULT_MEDIA_TYPE
