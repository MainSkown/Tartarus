import asyncio
import logging
import shutil
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from typing import Annotated

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Response,
    UploadFile,
)
from fastapi.exceptions import RequestValidationError
from opensearchpy.exceptions import OpenSearchException
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.analyses.deadline import MAX_RUN_S, at_the_latest, extended_deadline
from app.analyses.guest_badges import badges_by_guest
from app.analyses.guest_choice import GuestRefusedError, PackageNotAcceptedError, recorded_guest
from app.analyses.memory_disk import FreeSpaceProbe, MemoryDumpRefusedError
from app.analyses.memory_import import image_task_id, is_memory_image_import
from app.analyses.monitor import monitor_started
from app.analyses.ports import RunnerControl
from app.analyses.submission import AnalysisSubmitter, discard_unreferenced_sample
from app.api.dependencies import (
    get_cape,
    get_cape_storage_path,
    get_event_index,
    get_exports_path,
    get_free_space_probe,
    get_guest_control,
    get_import_submitter,
    get_imports_dir,
    get_runner,
    get_sample_store,
    require_analysis,
)
from app.cape.client import CapeClient
from app.cape.errors import CapeError, CapeTaskNotFound
from app.db.analysis_repository import (
    REINGESTABLE_STATUSES,
    AnalysisFilter,
    begin_reingest,
    cancel_if_queued,
    count_analyses,
    delete_analysis,
    list_analyses,
    queue_positions,
    update_analysis,
)
from app.db.annotation_repository import analysis_level_tags
from app.db.job_repository import has_active_job
from app.db.models import Analysis
from app.db.models.analysis import ACTIVE_STATUSES, AnalysisStatus
from app.db.session import get_session
from app.guest.client import GuestControl
from app.guest.errors import GuestControlError
from app.imports.upload import (
    ImportSubmitter,
    ImportTooLargeError,
    UnsupportedImportError,
    import_directory,
)
from app.jobs.exports import remove_analysis_exports
from app.samples.store import (
    EmptySampleError,
    SampleStore,
    SampleTooLargeError,
)
from app.schemas.analysis import AnalysisRead
from app.schemas.analysis_requests import (
    AnalysisCreated,
    AnalysisOptions,
    AnalysisPage,
    ExtendRequest,
)
from app.search.index import EventIndex

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/analyses", tags=["analyses"])

MAX_PAGE_SIZE = 200
DEFAULT_OPTIONS_JSON = "{}"


def parse_options(
    options: Annotated[
        str,
        Form(
            description=(
                "JSON object: `route`, `timeout` (60 to 1200 seconds), `package` (one the guest's "
                "profile lists), `interactive` (a desktop to drive; the run then lasts the whole "
                "timeout), `memory_dump` (dump the guest's RAM and read it; needs free disk), "
                "`keep_memory_dump` (keep the dump afterwards; only with `memory_dump`) and "
                "`guest` (a ready guest; the default guest when omitted)."
            )
        ),
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
    store: Annotated[SampleStore, Depends(get_sample_store)],
    guests: Annotated[GuestControl, Depends(get_guest_control)],
    runner: Annotated[RunnerControl, Depends(get_runner)],
    free_space: Annotated[FreeSpaceProbe, Depends(get_free_space_probe)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AnalysisCreated:
    """Stores the sample and queues an analysis on the chosen guest, or on the default guest.

    `409` when the guest does not exist or is not ready, when no guest has been built or is ready,
    and while any guest is being built or tested, and for a memory dump when the CAPE storage has
    less free disk than the dump needs (the message gives both numbers); `422` for a package the
    guest does not accept; `502` when the guest control service cannot be asked. `warnings` is
    filled when the submission was accepted with little free disk left.
    """
    try:
        submitted = await AnalysisSubmitter(store, guests, runner, free_space).submit_with_warnings(
            session, file, file.filename or "", options
        )
    except (GuestRefusedError, MemoryDumpRefusedError) as refused:
        raise HTTPException(409, str(refused)) from None
    except PackageNotAcceptedError as refused:
        raise RequestValidationError(
            [{"loc": ("body", "options", "package"), "msg": str(refused), "type": "value_error"}]
        ) from None
    except EmptySampleError:
        raise _rejected_file("The uploaded file is empty", "value_error.empty") from None
    except SampleTooLargeError as too_large:
        raise HTTPException(413, f"The file is larger than {too_large.max_bytes} bytes") from None
    read_back = await _read_one(session, guests, submitted.analysis)
    return AnalysisCreated(**read_back.model_dump(), warnings=submitted.warnings)


@router.post("/import", status_code=201)
async def import_capture(
    file: Annotated[UploadFile, File(description="A PCAP or PCAPNG capture.")],
    importer: Annotated[ImportSubmitter, Depends(get_import_submitter)],
    session: Annotated[AsyncSession, Depends(get_session)],
    guests: Annotated[GuestControl, Depends(get_guest_control)],
) -> AnalysisRead:
    """Queues an `imported` analysis of a PCAP or PCAPNG capture (up to 512 MiB), run in no guest.

    `415` when the file is not a capture, and for a memory image, which goes to
    `POST /analyses/import/memory-image`; `413` over the size limit; `422` for an empty file.
    """
    return await _import(importer, session, guests, file, accept_memory_image=False)


@router.post("/import/memory-image", status_code=201)
async def import_memory_image(
    file: Annotated[UploadFile, File(description="A memory image, or a PCAP or PCAPNG capture.")],
    importer: Annotated[ImportSubmitter, Depends(get_import_submitter)],
    session: Annotated[AsyncSession, Depends(get_session)],
    guests: Annotated[GuestControl, Depends(get_guest_control)],
) -> AnalysisRead:
    """Queues an `imported` analysis of a memory image (up to 5 GiB), which runs no guest.

    The path exists apart from `POST /analyses/import` because the reverse proxy streams uploads
    to it unbuffered, to a larger limit. A capture is accepted here too, with the capture limit.
    `415` when the file is neither; `413` over the size limit of its kind; `422` for an empty file.
    """
    return await _import(importer, session, guests, file, accept_memory_image=True)


@router.get("", name="list")
async def list_all(  # noqa: PLR0913 - one parameter per filter
    session: Annotated[AsyncSession, Depends(get_session)],
    guests: Annotated[GuestControl, Depends(get_guest_control)],
    *,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    q: Annotated[str | None, Query(description="Substring of the file name or the SHA256.")] = None,
    status: AnalysisStatus | None = None,
    tag: Annotated[
        str | None, Query(description="Only analyses carrying this tag on the analysis itself.")
    ] = None,
) -> AnalysisPage:
    """Newest first; `total` counts every match, not just this page."""
    filters = AnalysisFilter(q=q, status=status, tag=tag)
    items = await list_analyses(session, filters, limit=limit, offset=offset)
    return AnalysisPage(
        items=await _read_all(session, guests, items),
        total=await count_analyses(session, filters),
    )


@router.get("/{analysis_id}")
async def read(
    analysis_id: int,
    session: Annotated[AsyncSession, Depends(get_session)],
    guests: Annotated[GuestControl, Depends(get_guest_control)],
) -> AnalysisRead:
    return await _read_one(session, guests, await require_analysis(session, analysis_id))


@router.post("/{analysis_id}/cancel")
async def cancel(
    analysis_id: int,
    session: Annotated[AsyncSession, Depends(get_session)],
    guests: Annotated[GuestControl, Depends(get_guest_control)],
) -> AnalysisRead:
    """Only a queued analysis can be cancelled; once it has started, `409`."""
    analysis = await require_analysis(session, analysis_id)
    if not await cancel_if_queued(session, analysis_id):
        raise HTTPException(409, f"Analysis {analysis_id} is no longer queued")
    await session.refresh(analysis)
    return await _read_one(session, guests, analysis)


@router.post("/{analysis_id}/reingest")
async def reingest(
    analysis_id: int,
    session: Annotated[AsyncSession, Depends(get_session)],
    runner: Annotated[RunnerControl, Depends(get_runner)],
    guests: Annotated[GuestControl, Depends(get_guest_control)],
) -> AnalysisRead:
    """Indexes a finished analysis's report again. `409` unless it is `done` or `report_failed`,
    or while an analysis is active.
    """
    analysis = await require_analysis(session, analysis_id)
    started = await begin_reingest(session, analysis_id)
    await session.refresh(analysis)
    if not started:
        raise HTTPException(409, _reason_not_reingestible(analysis))
    runner.nudge()
    return await _read_one(session, guests, analysis)


@router.post("/{analysis_id}/finish")
async def finish(
    analysis_id: int,
    session: Annotated[AsyncSession, Depends(get_session)],
    guests: Annotated[GuestControl, Depends(get_guest_control)],
    storage: Annotated[Path, Depends(get_cape_storage_path)],
) -> AnalysisRead:
    """Ends a running analysis early, the way an interactive run is ended.

    The guest stops within about a second and the analysis then moves on to processing by itself,
    so the status answered is still `running`. Asking again is harmless. `409` unless the analysis
    is `running` and its monitor has started in the guest (CAPE says `running` about 14 s earlier,
    and ending the run in that gap leaves the guest agent dead, or the analysis records no guest);
    `502` when the guest control service cannot reach the guest agent.
    """
    analysis = await require_analysis(session, analysis_id)
    if analysis.status is not AnalysisStatus.RUNNING:
        raise HTTPException(409, _reason_not_finishable(analysis))
    if analysis.cape_task_id is None:
        raise HTTPException(409, f"Analysis {analysis_id} has no CAPE task to end")
    if not monitor_started(storage, analysis.cape_task_id):
        raise HTTPException(
            409,
            f"Analysis {analysis_id} has not started in the guest yet: wait a few seconds",
        )
    guest = recorded_guest(analysis.options)
    if guest is None:
        raise HTTPException(409, f"Analysis {analysis_id} records no guest to end its run on")
    try:
        await guests.finish_task(analysis.cape_task_id, guest)
    except GuestControlError as error:
        raise HTTPException(502, f"The run could not be ended: {error}") from None
    return await _read_one(session, guests, analysis)


@router.post("/{analysis_id}/extend")
async def extend(
    analysis_id: int,
    extension: ExtendRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
    guests: Annotated[GuestControl, Depends(get_guest_control)],
) -> AnalysisRead:
    """Moves the deadline of a running interactive run later by `seconds` (1 to 600).

    The backend ends the run at its deadline, as `POST /finish` would, and the live status counts
    down to the new one. The deadline never moves past 20 minutes after the start, the longest CAPE
    lets a task run: the new deadline is the earlier of the current one plus `seconds` and that
    limit. `409` with the reason when the analysis is not an interactive run, is not `running`, has
    not started in the guest yet, or is already at the 20-minute limit. `422` when `seconds` is not
    from 1 to 600.
    """
    analysis = await require_analysis(session, analysis_id)
    await update_analysis(
        session, analysis_id, deadline_at=_extended_deadline_of(analysis, extension.seconds)
    )
    return await _read_one(session, guests, analysis)


@router.delete("/{analysis_id}", status_code=204)
async def delete(  # noqa: PLR0913 - one argument per resource the analysis owns
    analysis_id: int,
    session: Annotated[AsyncSession, Depends(get_session)],
    *,
    cape: Annotated[CapeClient, Depends(get_cape)],
    index: Annotated[EventIndex, Depends(get_event_index)],
    store: Annotated[SampleStore, Depends(get_sample_store)],
    exports: Annotated[Path, Depends(get_exports_path)],
    imports: Annotated[Path, Depends(get_imports_dir)],
    guests: Annotated[GuestControl, Depends(get_guest_control)],
) -> Response:
    """Removes the analysis, its CAPE task, its event index, its exported files, its upload and
    the findings of an imported memory image, and its sample once unused. `409` while the
    analysis is active or has a job (an export) in progress.
    """
    analysis = await require_analysis(session, analysis_id)
    if analysis.status in ACTIVE_STATUSES:
        raise HTTPException(409, f"Analysis {analysis_id} is still {analysis.status.value}")
    if await has_active_job(session, analysis_id):
        raise HTTPException(409, f"Analysis {analysis_id} has an export in progress")
    if analysis.cape_task_id is not None:
        await _delete_cape_task(cape, analysis.cape_task_id)
    await _drop_event_index(index, analysis_id)
    await _remove_exports(exports, analysis_id)
    await _remove_import(imports, analysis_id)
    await _remove_image_findings(guests, analysis)
    await delete_analysis(session, analysis_id)
    await discard_unreferenced_sample(session, store, analysis.sample_sha256)
    return Response(status_code=204)


def _reason_not_reingestible(analysis: Analysis) -> str:
    if analysis.status not in REINGESTABLE_STATUSES:
        return (
            f"Analysis {analysis.id} is {analysis.status.value}; "
            "only a done or report_failed analysis can be re-ingested"
        )
    return f"Analysis {analysis.id} cannot be re-ingested while an analysis is active"


def _extended_deadline_of(analysis: Analysis, seconds: int) -> datetime:
    current, started = analysis.deadline_at, analysis.started_at
    if analysis.options.get("interactive") is not True:
        raise HTTPException(
            409,
            f"Analysis {analysis.id} is not an interactive run: "
            "only an interactive run can be extended",
        )
    if analysis.status is not AnalysisStatus.RUNNING:
        raise HTTPException(
            409,
            f"Analysis {analysis.id} is {analysis.status.value}: "
            "only a running analysis can be extended",
        )
    if current is None or started is None:
        raise HTTPException(409, "The run has not started in the guest yet: wait a few seconds")
    if at_the_latest(current, started):
        raise HTTPException(409, f"The run is already at its longest ({MAX_RUN_S // 60} minutes)")
    return extended_deadline(current, started, seconds)


def _reason_not_finishable(analysis: Analysis) -> str:
    status = analysis.status
    if status is AnalysisStatus.QUEUED:
        return f"Analysis {analysis.id} is queued; it has not started, cancel it instead"
    if status is AnalysisStatus.STARTING:
        return f"Analysis {analysis.id} is starting and not running yet; try again once it runs"
    return f"Analysis {analysis.id} is {status.value}: its run is already over"


async def _read_all(
    session: AsyncSession, guests: GuestControl, analyses: Sequence[Analysis]
) -> list[AnalysisRead]:
    ids = [analysis.id for analysis in analyses]
    positions = await queue_positions(session, ids)
    tags = await analysis_level_tags(session, ids)
    named = {analysis.id: recorded_guest(analysis.options) for analysis in analyses}
    badges = await badges_by_guest(guests, named.values())
    return [
        AnalysisRead.model_validate(analysis).model_copy(
            update={
                "queue_position": positions.get(analysis.id),
                "tags": tags.get(analysis.id, []),
                "guest": named[analysis.id],
                "guest_badges": badges.get(named[analysis.id] or "", []),
            }
        )
        for analysis in analyses
    ]


async def _read_one(
    session: AsyncSession, guests: GuestControl, analysis: Analysis
) -> AnalysisRead:
    return (await _read_all(session, guests, [analysis]))[0]


def _rejected_file(message: str, error_type: str) -> RequestValidationError:
    return RequestValidationError([{"loc": ("body", "file"), "msg": message, "type": error_type}])


async def _delete_cape_task(cape: CapeClient, task_id: int) -> None:
    # A CAPE task that cannot be removed must not make the analysis undeletable.
    try:
        task_status = await cape.task_status(task_id)
        await cape.delete_task(task_id, task_status=task_status)
    except CapeTaskNotFound:
        return
    except CapeError as error:
        logger.warning("CAPE task %s was left behind: %s", task_id, error)


async def _drop_event_index(index: EventIndex, analysis_id: int) -> None:
    # An index that cannot be removed must not make the analysis undeletable.
    try:
        await index.drop(analysis_id)
    except OpenSearchException as error:
        logger.warning("The event index of analysis %s was left behind: %s", analysis_id, error)


async def _import(
    importer: ImportSubmitter,
    session: AsyncSession,
    guests: GuestControl,
    file: UploadFile,
    *,
    accept_memory_image: bool,
) -> AnalysisRead:
    try:
        analysis = await importer.submit(
            session, file, file.filename or "", accept_memory_image=accept_memory_image
        )
    except UnsupportedImportError as unsupported:
        raise HTTPException(415, str(unsupported)) from None
    except ImportTooLargeError as too_large:
        raise HTTPException(413, f"The file is larger than {too_large.max_bytes} bytes") from None
    except EmptySampleError:
        raise _rejected_file("The uploaded file is empty", "value_error.empty") from None
    return await _read_one(session, guests, analysis)


async def _remove_import(imports: Path, analysis_id: int) -> None:
    # An uploaded file that cannot be removed must not make the analysis undeletable.
    try:
        await asyncio.to_thread(shutil.rmtree, import_directory(imports, analysis_id), True)
    except OSError as error:
        logger.warning("The upload of analysis %s was left behind: %s", analysis_id, error)


async def _remove_image_findings(guests: GuestControl, analysis: Analysis) -> None:
    # CAPE owns its storage, so the control service removes what a memory image's scan wrote there.
    # Findings that cannot be removed must not make the analysis undeletable.
    if not is_memory_image_import(analysis):
        return
    try:
        await guests.delete_image_findings(image_task_id(analysis.id))
    except GuestControlError as error:
        logger.warning("The findings of analysis %s were left behind: %s", analysis.id, error)


async def _remove_exports(exports: Path, analysis_id: int) -> None:
    # Exported files that cannot be removed must not make the analysis undeletable.
    try:
        await asyncio.to_thread(remove_analysis_exports, exports, analysis_id)
    except OSError as error:
        logger.warning("The exports of analysis %s were left behind: %s", analysis_id, error)
