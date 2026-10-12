from collections.abc import Mapping
from typing import Annotated, cast

from fastapi import APIRouter, Depends, Request

from app.health import HealthCheck, SystemHealth, collect_health

router = APIRouter(prefix="/system", tags=["system"])


def get_health_checks(request: Request) -> Mapping[str, HealthCheck]:
    return cast(Mapping[str, HealthCheck], request.app.state.health_checks)


@router.get("/health")
async def health(
    checks: Annotated[Mapping[str, HealthCheck], Depends(get_health_checks)],
) -> SystemHealth:
    """Status of each component. Always answers 200 while the backend itself is alive."""
    return await collect_health(checks)
