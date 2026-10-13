from typing import Protocol

from app.cape.errors import (
    CapeAuthError,
    CapeError,
    CapeNotConfigured,
    CapeUnreachable,
)
from app.cape.models import CuckooStatus, Machine
from app.health import ComponentHealth, HealthStatus


class CapeProbe(Protocol):
    async def cuckoo_status(self) -> CuckooStatus: ...

    async def list_machines(self) -> list[Machine]: ...


def _down(error: CapeError) -> ComponentHealth:
    return ComponentHealth(status=HealthStatus.DOWN, message=_down_message(error))


def _down_message(error: CapeError) -> str:
    if isinstance(error, CapeUnreachable):
        return "CAPE is unreachable"
    if isinstance(error, CapeAuthError):
        return "CAPE refused the API token"
    if isinstance(error, CapeNotConfigured):
        return "CAPE_API_TOKEN is not set"
    return "CAPE answered with an error"


class CapeCheck:
    def __init__(self, cape: CapeProbe) -> None:
        self._cape = cape

    async def check(self) -> ComponentHealth:
        try:
            await self._cape.cuckoo_status()
        except CapeError as error:
            return _down(error)
        return ComponentHealth(status=HealthStatus.OK)


class GuestCheck:
    """Ready means listed: an idle guest is `poweroff` until CAPE restores it.

    A locked guest is running a task. It is healthy, and new samples queue behind the task, so
    being busy must not stop a submission; the message says so, for the header's tooltip.
    """

    def __init__(self, cape: CapeProbe, guest_label: str) -> None:
        self._cape = cape
        self._guest_label = guest_label

    async def check(self) -> ComponentHealth:
        try:
            machines = await self._cape.list_machines()
        except CapeError as error:
            return _down(error)
        guest = next((machine for machine in machines if machine.label == self._guest_label), None)
        if guest is None:
            return ComponentHealth(
                status=HealthStatus.DEGRADED,
                message=f"CAPE does not list a guest named {self._guest_label}",
            )
        if guest.locked:
            return ComponentHealth(
                status=HealthStatus.OK,
                message=f"guest {self._guest_label} is busy with an analysis",
            )
        return ComponentHealth(status=HealthStatus.OK)
