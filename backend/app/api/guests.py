from typing import Annotated

from fastapi import APIRouter, Depends, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_guest_control, require_no_analysis_needing_a_guest
from app.db.session import get_session
from app.guest.client import GuestControl
from app.guest.schemas import Guest, GuestProfile, HealthCheckResult, MediaEntry

router = APIRouter(prefix="/guests", tags=["guests"])

GuestControlDependency = Annotated[GuestControl, Depends(get_guest_control)]


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


@router.get("/{name}")
async def read(name: str, control: GuestControlDependency) -> Guest:
    """One guest's record. `404` when no guest has that name."""
    return await control.guest(name)


@router.delete("/{name}", status_code=204)
async def delete(
    name: str,
    control: GuestControlDependency,
    session: Annotated[AsyncSession, Depends(get_session)],
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
    session: Annotated[AsyncSession, Depends(get_session)],
) -> HealthCheckResult:
    """Runs the guest's health checks now: the VM is defined, its snapshot exists, CAPE lists it,
    and its agent answers after the snapshot is restored (which takes up to two minutes). `409`
    while an analysis is queued, starting or running, or while a build is running; `404` when no
    guest has that name.
    """
    await require_no_analysis_needing_a_guest(session, "checked")
    return await control.check(name)
