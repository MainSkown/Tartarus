from typing import Protocol

from app.guest.errors import GuestControlError, GuestControlUnreachable
from app.guest.schemas import Guest
from app.health import ComponentHealth, HealthStatus


class GuestLister(Protocol):
    async def guests(self) -> list[Guest]: ...


class GuestCheck:
    """Aggregate health of every guest, from the guest control service's records alone.

    CAPE is not asked: a `ready` guest that CAPE has locked is running an analysis, which is
    healthy, and a submission queues behind it, so being busy never counts against a guest.
    """

    def __init__(self, control: GuestLister) -> None:
        self._control = control

    async def check(self) -> ComponentHealth:
        try:
            guests = await self._control.guests()
        except GuestControlUnreachable:
            return _down("the guest control service is not reachable")
        except GuestControlError:
            return _down("the guest control service answered with an error")
        return _aggregate(guests)


def _down(message: str) -> ComponentHealth:
    return ComponentHealth(status=HealthStatus.DOWN, message=message)


def _aggregate(guests: list[Guest]) -> ComponentHealth:
    if not guests:
        return _down("no guest has been built")
    not_ready = [f"{guest.name} is {guest.state}" for guest in guests if guest.state != "ready"]
    if not not_ready:
        return ComponentHealth(status=HealthStatus.OK)
    if len(not_ready) == len(guests):
        return _down(f"no guest is ready ({', '.join(not_ready)})")
    return ComponentHealth(status=HealthStatus.DEGRADED, message=", ".join(not_ready))
