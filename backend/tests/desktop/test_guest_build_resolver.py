import asyncio

import pytest

from app.desktop.admission import (
    CLOSE_CONFLICT,
    CLOSE_NOT_AVAILABLE_YET,
    CLOSE_NOT_FOUND,
    CloseRequest,
)
from app.desktop.guest_build import GuestBuildResolver
from app.desktop.resolver import CheckUnavailableError, VncTarget
from app.guest.schemas import BuildProgress
from tests.desktop.stubs import (
    BUILD_ID,
    BUILD_SCREEN,
    GUEST,
    StubGuestControl,
    build_status,
    building_guest,
    control_refused,
    control_unreachable,
    guest_building_with_a_desktop,
)

POLL_S = 0.005
PATIENCE_S = 0.15

NO_DESKTOP = CloseRequest(CLOSE_CONFLICT, "this guest has no build that shows a desktop")
NOT_FOUND = CloseRequest(CLOSE_NOT_FOUND, "guest not found")
NOT_YET = CloseRequest(CLOSE_NOT_AVAILABLE_YET, "desktop not available yet")


def resolver_for(control: StubGuestControl, name: str = GUEST) -> GuestBuildResolver:
    return GuestBuildResolver(control, name)


async def wait_for(resolver: GuestBuildResolver) -> VncTarget | CloseRequest:
    return await resolver.wait_for_target(poll_interval_s=POLL_S, patience_s=PATIENCE_S)


async def test_a_guest_whose_running_build_shows_a_desktop_is_admitted() -> None:
    control = guest_building_with_a_desktop()

    assert await resolver_for(control).refusal() is None


async def test_a_build_paused_at_a_desktop_step_is_admitted() -> None:
    control = guest_building_with_a_desktop()
    control.builds[BUILD_ID] = build_status(status="paused")

    assert await resolver_for(control).refusal() is None


async def test_an_unknown_guest_is_not_found() -> None:
    control = StubGuestControl()

    assert await resolver_for(control).refusal() == NOT_FOUND


async def test_a_guest_without_a_build_has_no_desktop() -> None:
    control = StubGuestControl(guests={GUEST: building_guest(state="ready", build_id=None)})

    assert await resolver_for(control).refusal() == NO_DESKTOP
    assert ("build", BUILD_ID) not in control.calls


async def test_a_build_the_control_service_no_longer_knows_has_no_desktop() -> None:
    control = StubGuestControl(guests={GUEST: building_guest()})

    assert await resolver_for(control).refusal() == NO_DESKTOP


async def test_a_build_not_at_a_desktop_step_has_no_desktop() -> None:
    control = guest_building_with_a_desktop()
    control.builds[BUILD_ID] = build_status(desktop=False)

    assert await resolver_for(control).refusal() == NO_DESKTOP


@pytest.mark.parametrize("status", ["succeeded", "failed"])
async def test_a_finished_build_has_no_desktop_even_if_the_service_still_says_so(
    status: BuildProgress,
) -> None:
    control = guest_building_with_a_desktop()
    control.builds[BUILD_ID] = build_status(status=status, desktop=True)

    assert await resolver_for(control).refusal() == NO_DESKTOP


async def test_a_ready_guest_is_served_no_desktop_here() -> None:
    control = guest_building_with_a_desktop()
    control.guests[GUEST] = building_guest(state="ready")
    control.builds[BUILD_ID] = build_status(status="succeeded", desktop=False)

    assert await resolver_for(control).refusal() == NO_DESKTOP


@pytest.mark.parametrize("name", ["../etc", "Lab1", "a", "lab_1", "1lab", "x" * 33, "lab1/x", ""])
async def test_a_name_that_is_not_a_slug_is_not_found_without_asking_the_service(
    name: str,
) -> None:
    control = guest_building_with_a_desktop()

    assert await resolver_for(control, name).refusal() == NOT_FOUND
    assert control.calls == []


@pytest.mark.parametrize("failure", [control_unreachable(), control_refused("guest", 422)])
async def test_a_control_service_that_fails_is_unavailable_not_a_refusal(
    failure: Exception,
) -> None:
    control = guest_building_with_a_desktop()
    control.error = failure  # type: ignore[assignment]

    with pytest.raises(CheckUnavailableError):
        await resolver_for(control).refusal()


async def test_the_target_is_the_display_the_control_service_names() -> None:
    control = guest_building_with_a_desktop()

    assert await wait_for(resolver_for(control)) == VncTarget(BUILD_SCREEN.host, BUILD_SCREEN.port)


async def test_a_domain_that_starts_late_is_waited_for() -> None:
    control = guest_building_with_a_desktop()
    control.screens.clear()
    control.screen_once_asked = (3, BUILD_SCREEN)

    target = await wait_for(resolver_for(control))

    assert target == VncTarget(BUILD_SCREEN.host, BUILD_SCREEN.port)
    assert [call for call, _ in control.calls].count("display") == 3


async def test_a_display_that_never_appears_is_not_available_yet() -> None:
    control = guest_building_with_a_desktop()
    control.screens.clear()

    assert await wait_for(resolver_for(control)) == NOT_YET


async def test_the_build_leaving_its_desktop_step_while_waiting_is_a_conflict() -> None:
    control = guest_building_with_a_desktop()
    control.screens.clear()
    control.builds[BUILD_ID] = build_status(desktop=False)

    assert await wait_for(resolver_for(control)) == NO_DESKTOP


async def test_a_control_service_that_stays_unreachable_ends_in_a_server_error() -> None:
    control = guest_building_with_a_desktop()
    control.error = control_unreachable()

    refusal = await wait_for(resolver_for(control))

    assert refusal == CloseRequest(1011, "guest control service unavailable")


async def test_a_control_service_that_fails_for_a_moment_is_waited_out() -> None:
    control = guest_building_with_a_desktop()
    control.error = control_unreachable()
    resolver = resolver_for(control)

    async with asyncio.TaskGroup() as group:
        waiting = group.create_task(wait_for(resolver))
        await asyncio.sleep(POLL_S * 3)
        control.error = None

    assert waiting.result() == VncTarget(BUILD_SCREEN.host, BUILD_SCREEN.port)
