"""The desktop of a guest while it is being built: the install, the provisioning and the pauses.

Only a build that is at a desktop step (running or paused) opens it; the control service reports
that as the build's `desktop`. Once the build ends, the desktop of a ready guest is an analysis's.
"""

import asyncio
import logging
from collections.abc import Awaitable
from typing import Protocol

from app.desktop.admission import (
    CLOSE_CONFLICT,
    CLOSE_NOT_AVAILABLE_YET,
    CLOSE_NOT_FOUND,
    CLOSE_SERVER_ERROR,
    CloseRequest,
)
from app.desktop.resolver import CheckUnavailableError, VncTarget
from app.guest.errors import GuestControlError, GuestControlRejected
from app.guest.identifiers import GUEST_NAME
from app.guest.schemas import BuildStatus, Guest, GuestDisplay

logger = logging.getLogger(__name__)

ACTIVE_BUILD_STATUSES = frozenset({"running", "paused"})

NOT_FOUND = CloseRequest(CLOSE_NOT_FOUND, "guest not found")
NO_DESKTOP = CloseRequest(CLOSE_CONFLICT, "this guest has no build that shows a desktop")
NOT_AVAILABLE_YET = CloseRequest(CLOSE_NOT_AVAILABLE_YET, "desktop not available yet")
CONTROL_UNAVAILABLE = "guest control service unavailable"


class BuildControl(Protocol):
    """The part of `GuestControl` the build desktop uses."""

    async def guest(self, name: str) -> Guest: ...

    async def build(self, build_id: str) -> BuildStatus: ...

    async def display(self, name: str) -> GuestDisplay: ...


class GuestBuildResolver:
    ended_reason = "the build no longer shows a desktop"

    def __init__(self, control: BuildControl, name: str) -> None:
        self._control = control
        self._name = name
        self.label = f"guest {name}"

    async def refusal(self) -> CloseRequest | None:
        if not GUEST_NAME.fullmatch(self._name):
            return NOT_FOUND
        guest = await _none_when_missing(self._control.guest(self._name))
        if guest is None:
            return NOT_FOUND
        if guest.build_id is None:
            return NO_DESKTOP
        build = await _none_when_missing(self._control.build(guest.build_id))
        return None if build and _shows_a_desktop(build) else NO_DESKTOP

    async def wait_for_target(
        self, *, poll_interval_s: float, patience_s: float
    ) -> VncTarget | CloseRequest:
        """The domain is defined before it runs, so its display appears a little after the build
        reaches the step: keep asking until it does or the patience runs out.
        """
        deadline = asyncio.get_running_loop().time() + patience_s
        failure: CheckUnavailableError | None = None
        while True:
            try:
                if (refusal := await self.refusal()) is not None:
                    return refusal
                display = await _none_when_missing(self._control.display(self._name))
            except CheckUnavailableError as error:
                failure = error
            else:
                failure = None
                if display is not None:
                    return VncTarget(display.host, display.port)
            if asyncio.get_running_loop().time() >= deadline:
                return _unavailable(failure) if failure else NOT_AVAILABLE_YET
            await asyncio.sleep(poll_interval_s)


def _unavailable(failure: CheckUnavailableError) -> CloseRequest:
    return CloseRequest(CLOSE_SERVER_ERROR, failure.reason)


def _shows_a_desktop(build: BuildStatus) -> bool:
    return build.desktop and build.status in ACTIVE_BUILD_STATUSES


async def _none_when_missing[T](asking: Awaitable[T]) -> T | None:
    try:
        return await asking
    except GuestControlRejected as error:
        if error.status != 404:  # noqa: PLR2004 - HTTP "not found"
            raise CheckUnavailableError(CONTROL_UNAVAILABLE) from error
        return None
    except GuestControlError as error:
        logger.debug("the guest control service could not be asked: %s", error)
        raise CheckUnavailableError(CONTROL_UNAVAILABLE) from error
