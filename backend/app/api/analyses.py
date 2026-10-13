import logging
from typing import Annotated, cast

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
)
from fastapi.exceptions import RequestValidationError
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.analyses.ports import RunnerControl
from app.api.dependencies import get_cape, get_runner, get_sample_store
from app.cape.client import CapeClient
from app.cape.errors import CapeError, CapeTaskNotFound
from app.db.analysis_repository import (
    AnalysisFilter,
    add_sample_if_new,
    cancel_if_queued,
    count_analyses,
    create_analysis,
    delete_analysis,
    delete_sample_if_unreferenced,
    get_analysis,
    get_sample,
    list_analyses,
)
from app.db.models import Analysis, Sample
from app.db.models.analysis import ACTIVE_STATUSES, AnalysisStatus
from app.db.session import get_session
from app.health import HealthCheck, HealthStatus, evaluate
from app.samples.store import (
    EmptySampleError,
    SampleStore,
    SampleTooLargeError,
    StoredSample,
    safe_file_name,
)
from app.schemas.analysis import AnalysisRead
from app.schemas.analysis_requests import AnalysisOptions, AnalysisPage

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/analyses", tags=["analyses"])

MAX_PAGE_SIZE = 200
DEFAULT_OPTIONS_JSON = "{}"


def get_guest_check(request: Request) -> HealthCheck:
    return cast(HealthCheck, request.app.state.health_checks["guest"])


def parse_options(
    options: Annotated[
        str,
        Form(description="JSON object: `route`, `timeout` (60 to 1200 seconds) and `package`."),
    ] = DEFAULT_OPTIONS_JSON,
) -> AnalysisOptions:
    try:
        return AnalysisOptions.model_validate_json(options)
    except ValidationError as invalid:
        raise RequestValidationError(
            [
                {**error, "loc": ("body", "options", *error["loc"])}
                for error in invalid.errors(include_url=False, include_context=False)
            ]
        ) from None


@router.post("", status_code=201)
async def create(  # noqa: PLR0913 - one argument per dependency of the submission
    file: Annotated[UploadFile, File(description="The sample to detonate.")],
    options: Annotated[AnalysisOptions, Depends(parse_options)],
    *,
    guest: Annotated[HealthCheck, Depends(get_guest_check)],
    store: Annotated[SampleStore, Depends(get_sample_store)],
    runner: Annotated[RunnerControl, Depends(get_runner)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AnalysisRead:
    """Stores the sample and queues an analysis. `409` while the analysis guest is not ready."""
    await _require_ready_guest(guest)
    filename = safe_file_name(file.filename or "")
    stored = await _store_upload(store, file, filename)
    try:
        analysis = await _queue_analysis(session, stored, filename, options)
    except Exception:
        await session.rollback()
        await _discard_unreferenced_sample(session, store, stored.sha256)
        raise
    runner.nudge()
    return AnalysisRead.model_validate(analysis)


@router.get("", name="list")
async def list_all(
    session: Annotated[AsyncSession, Depends(get_session)],
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    q: Annotated[str | None, Query(description="Substring of the file name or the SHA256.")] = None,
    status: AnalysisStatus | None = None,
) -> AnalysisPage:
    """Newest first; `total` counts every match, not just this page."""
    filters = AnalysisFilter(q=q, status=status)
    items = await list_analyses(session, filters, limit=limit, offset=offset)
    return AnalysisPage(
        items=[AnalysisRead.model_validate(item) for item in items],
        total=await count_analyses(session, filters),
    )


@router.get("/{analysis_id}")
async def read(
    analysis_id: int, session: Annotated[AsyncSession, Depends(get_session)]
) -> AnalysisRead:
    return AnalysisRead.model_validate(await _existing(session, analysis_id))


@router.post("/{analysis_id}/cancel")
async def cancel(
    analysis_id: int, session: Annotated[AsyncSession, Depends(get_session)]
) -> AnalysisRead:
    """Only a queued analysis can be cancelled; once it has started, `409`."""
    analysis = await _existing(session, analysis_id)
    if not await cancel_if_queued(session, analysis_id):
        raise HTTPException(409, f"Analysis {analysis_id} is no longer queued")
    await session.refresh(analysis)
    return AnalysisRead.model_validate(analysis)


@router.delete("/{analysis_id}", status_code=204)
async def delete(
    analysis_id: int,
    session: Annotated[AsyncSession, Depends(get_session)],
    cape: Annotated[CapeClient, Depends(get_cape)],
    store: Annotated[SampleStore, Depends(get_sample_store)],
) -> Response:
    """Removes the analysis, its CAPE task, and its sample once nothing else uses it."""
    analysis = await _existing(session, analysis_id)
    if analysis.status in ACTIVE_STATUSES:
        raise HTTPException(409, f"Analysis {analysis_id} is still {analysis.status.value}")
    if analysis.cape_task_id is not None:
        await _delete_cape_task(cape, analysis.cape_task_id)
    await delete_analysis(session, analysis_id)
    await _discard_unreferenced_sample(session, store, analysis.sample_sha256)
    return Response(status_code=204)


async def _existing(session: AsyncSession, analysis_id: int) -> Analysis:
    analysis = await get_analysis(session, analysis_id)
    if analysis is None:
        raise HTTPException(404, f"Analysis {analysis_id} not found")
    return analysis


async def _require_ready_guest(guest: HealthCheck) -> None:
    health = await evaluate(guest)
    if health.status is not HealthStatus.OK:
        reason = f": {health.message}" if health.message else ""
        raise HTTPException(409, f"The analysis guest is not ready ({health.status.value}{reason})")


async def _store_upload(store: SampleStore, file: UploadFile, filename: str) -> StoredSample:
    try:
        return await store.save(file, filename)
    except EmptySampleError:
        raise _rejected_file("The uploaded file is empty", "value_error.empty") from None
    except SampleTooLargeError as too_large:
        raise HTTPException(413, f"The file is larger than {too_large.max_bytes} bytes") from None


def _rejected_file(message: str, error_type: str) -> RequestValidationError:
    return RequestValidationError([{"loc": ("body", "file"), "msg": message, "type": error_type}])


async def _queue_analysis(
    session: AsyncSession, stored: StoredSample, filename: str, options: AnalysisOptions
) -> Analysis:
    sample = Sample(
        sha256=stored.sha256,
        sha1=stored.sha1,
        md5=stored.md5,
        size=stored.size,
        original_name=filename,
        stored_path=str(stored.path),
    )
    try:
        await add_sample_if_new(session, sample)
    except IntegrityError:
        # `add_sample_if_new` is get-then-insert: another upload of the same file won the insert.
        await session.rollback()
    return await create_analysis(
        session,
        sample_sha256=stored.sha256,
        filename=filename,
        options=options.model_dump(),
    )


async def _discard_unreferenced_sample(
    session: AsyncSession, store: SampleStore, sha256: str
) -> None:
    row_removed = await delete_sample_if_unreferenced(session, sha256)
    if row_removed or await get_sample(session, sha256) is None:
        await store.delete(sha256)


async def _delete_cape_task(cape: CapeClient, task_id: int) -> None:
    # A CAPE task that cannot be removed must not make the analysis undeletable.
    try:
        task_status = await cape.task_status(task_id)
        await cape.delete_task(task_id, task_status=task_status)
    except CapeTaskNotFound:
        return
    except CapeError as error:
        logger.warning("CAPE task %s was left behind: %s", task_id, error)
