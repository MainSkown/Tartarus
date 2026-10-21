from collections.abc import Mapping
from typing import Annotated, cast

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.analyses.queue_view import queue_snapshot
from app.db.base import utc_now
from app.db.session import get_session
from app.health import HealthCheck, SystemHealth, collect_health
from app.schemas.system import QueueSnapshot

router = APIRouter(prefix="/system", tags=["system"])


def get_health_checks(request: Request) -> Mapping[str, HealthCheck]:
    return cast(Mapping[str, HealthCheck], request.app.state.health_checks)


@router.get("/health")
async def health(
    checks: Annotated[Mapping[str, HealthCheck], Depends(get_health_checks)],
) -> SystemHealth:
    """Status of each component. Always answers 200 while the backend itself is alive."""
    return await collect_health(checks)


@router.get("/queue")
async def queue(session: Annotated[AsyncSession, Depends(get_session)]) -> QueueSnapshot:
    """Analyses running now (oldest first, with seconds since they started) and the queued ones,
    each with its place on its guest's line; the same snapshot `/ws/system` pushes as `queue`.
    """
    return await queue_snapshot(session, utc_now())
