from typing import Protocol

from app.cape.errors import (
    CapeAuthError,
    CapeError,
    CapeNotConfigured,
    CapeUnreachable,
)
from app.cape.models import CuckooStatus
from app.health import ComponentHealth, HealthStatus


class CapeProbe(Protocol):
    async def cuckoo_status(self) -> CuckooStatus: ...


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
