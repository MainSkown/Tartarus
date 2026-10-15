from typing import Annotated, Any, cast

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_guest_control, require_no_analysis_needing_a_guest
from app.db.session import get_session
from app.guest.build_job import BuildTracking
from app.guest.client import GuestControl
from app.guest.schemas import (
    ActiveBuild,
    BuildStarted,
    BuildView,
    Guest,
    GuestProfile,
    HealthCheckResult,
    MediaEntry,
)

router = APIRouter(prefix="/guests", tags=["guests"])

DEFAULT_LOG_TAIL = 200
MAX_LOG_TAIL = 2000


def get_build_tracking(request: Request) -> BuildTracking:
    return cast(BuildTracking, request.app.state.build_tracking)


GuestControlDependency = Annotated[GuestControl, Depends(get_guest_control)]
BuildTrackingDependency = Annotated[BuildTracking, Depends(get_build_tracking)]
SessionDependency = Annotated[AsyncSession, Depends(get_session)]
# The control service validates the parameters and says which field is wrong; the backend only
# insists on an object.
ControlParams = Annotated[dict[str, Any], Body()]


@router.get("", name="list")
async def list_all(control: GuestControlDependency) -> list[Guest]:
    """Every guest with its state, resources, address, options and last self-test.

    A guest whose record cannot be read is listed with the state `broken` and the reason, so that
    it can be seen and deleted. `502` when the guest control service is not reachable.
    """
    return await control.guests()


# `media` and `profiles` come before `{name}`: a path is matched in order, and neither is a guest.
@router.get("/media")
async def media(control: GuestControlDependency) -> list[MediaEntry]:
    """Installation media found for the build wizard, one entry per image and the guest profile
    that recognised it, with the editions it offers. A file nothing recognised is listed with an
    `error` saying why.
    """
    return await control.media()


@router.get("/profiles")
async def profiles(control: GuestControlDependency) -> list[GuestProfile]:
    """The kinds of guest that can be built: the options to offer, the rules a name must follow,
    the badges a guest earns from its options, and the package names a sample may use.
    """
    return await control.profiles()


@router.post("/build", status_code=202)
async def start_build(
    params: ControlParams,
    control: GuestControlDependency,
    session: SessionDependency,
    tracking: BuildTrackingDependency,
) -> BuildStarted:
    """Starts building a guest from an installation medium and a job that follows the build.

    The body is the control service's build parameters (profile, name, media, options, identity,
    resources); it checks them and answers `422` with what is wrong with which field. `409`
    while an analysis is queued, starting or running, or while another build or clone runs.
    """
    await require_no_analysis_needing_a_guest(session, "built")
    return await _follow(control, tracking, await control.start_build(params))


@router.get("/builds/active")
async def active_build(tracking: BuildTrackingDependency) -> ActiveBuild:
    """The build a job is following now: its guest, build and job. `404` when none is."""
    tracked = tracking.active()
    if tracked is None:
        raise HTTPException(404, "No guest build is being followed")
    return ActiveBuild(build_id=tracked.build_id, guest=tracked.guest, job_id=tracked.job_id)


@router.get("/builds/{build_id}")
async def read_build(
    build_id: str,
    control: GuestControlDependency,
    tail: Annotated[int, Query(ge=1, le=MAX_LOG_TAIL)] = DEFAULT_LOG_TAIL,
) -> BuildView:
    """The build's status, steps, pause instructions and the last `tail` lines of its log.
    `404` when no build has that id.
    """
    build = await control.build(build_id)
    return BuildView(**build.model_dump(), log=await control.build_log(build_id, tail))


@router.post("/builds/{build_id}/resume", status_code=202)
async def resume_build(
    build_id: str,
    control: GuestControlDependency,
    session: SessionDependency,
    tracking: BuildTrackingDependency,
) -> BuildStarted:
    """Runs a failed build again from the step that stopped it, and follows it with a job.
    `409` while an analysis is queued, starting or running, or when the build is not failed.
    """
    await require_no_analysis_needing_a_guest(session, "built")
    await control.resume(build_id)
    return await _follow(control, tracking, build_id)


@router.post("/builds/{build_id}/restart", status_code=202)
async def restart_build(
    build_id: str,
    control: GuestControlDependency,
    session: SessionDependency,
    tracking: BuildTrackingDependency,
) -> BuildStarted:
    """Runs a failed build again from its first step, and follows it with a job. `409` while an
    analysis is queued, starting or running, or when the build is not failed.
    """
    await require_no_analysis_needing_a_guest(session, "built")
    await control.restart(build_id)
    return await _follow(control, tracking, build_id)


@router.post("/builds/{build_id}/continue", status_code=202)
async def continue_build(
    build_id: str,
    control: GuestControlDependency,
    session: SessionDependency,
    tracking: BuildTrackingDependency,
) -> BuildStarted:
    """Carries on a paused build once the analyst has done what the pause asked. The job that
    follows the build resumes by itself; none is started when one already follows it. `409`
    while an analysis is queued, starting or running, or when the build is not paused.
    """
    await require_no_analysis_needing_a_guest(session, "built")
    await control.continue_(build_id)
    return await _follow(control, tracking, build_id)


async def _follow(control: GuestControl, tracking: BuildTracking, build_id: str) -> BuildStarted:
    build = await control.build(build_id)
    tracked = await tracking.track(build.guest, build.id, build.kind)
    return BuildStarted(job_id=tracked.job_id, build_id=build.id, guest=build.guest)


@router.get("/{name}")
async def read(name: str, control: GuestControlDependency) -> Guest:
    """One guest's record. `404` when no guest has that name."""
    return await control.guest(name)


@router.delete("/{name}", status_code=204)
async def delete(
    name: str,
    control: GuestControlDependency,
    session: SessionDependency,
) -> Response:
    """Removes the guest: its VM, snapshot, disk and registration. Analyses that used it keep
    their data. `409` while an analysis is queued, starting or running, or when the guest is being
    built or cloned from; `404` when no guest has that name.
    """
    await require_no_analysis_needing_a_guest(session, "deleted")
    await control.delete_guest(name)
    return Response(status_code=204)


@router.post("/{name}/check")
async def check(
    name: str,
    control: GuestControlDependency,
    session: SessionDependency,
) -> HealthCheckResult:
    """Runs the guest's health checks now: the VM is defined, its snapshot exists, CAPE lists it,
    and its agent answers after the snapshot is restored (which takes up to two minutes). `409`
    while an analysis is queued, starting or running, or while a build is running; `404` when no
    guest has that name.
    """
    await require_no_analysis_needing_a_guest(session, "checked")
    return await control.check(name)


@router.post("/{name}/clone", status_code=202)
async def clone(
    name: str,
    params: ControlParams,
    control: GuestControlDependency,
    session: SessionDependency,
    tracking: BuildTrackingDependency,
) -> BuildStarted:
    """Clones a ready guest into a new one and starts a job that follows the clone.

    The body is the control service's clone parameters (the new name and the options that may
    change); it checks them and answers `422` with what is wrong with which field. `409` while an
    analysis is queued, starting or running, while another build or clone runs, or when the guest
    is not ready; `404` when no guest has that name. The answer's `guest` is the new guest.
    """
    await require_no_analysis_needing_a_guest(session, "cloned")
    return await _follow(control, tracking, await control.start_clone(name, params))
