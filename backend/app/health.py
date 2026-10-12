import asyncio
from collections.abc import Mapping
from enum import StrEnum
from typing import Protocol

from opensearchpy import AsyncOpenSearch
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

DEFAULT_TIMEOUT_S = 3.0


class HealthStatus(StrEnum):
    OK = "ok"
    DEGRADED = "degraded"
    DOWN = "down"


class ComponentHealth(BaseModel):
    status: HealthStatus
    message: str | None = None


class SystemHealth(BaseModel):
    postgres: ComponentHealth
    opensearch: ComponentHealth
    cape: ComponentHealth
    guest: ComponentHealth


class HealthCheck(Protocol):
    async def check(self) -> ComponentHealth: ...


class PostgresCheck:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def check(self) -> ComponentHealth:
        async with self._engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
        return ComponentHealth(status=HealthStatus.OK)


class OpenSearchCheck:
    def __init__(self, client: AsyncOpenSearch) -> None:
        self._client = client

    async def check(self) -> ComponentHealth:
        cluster_status = (await self._client.cluster.health())["status"]
        # Yellow is normal on a single node: replicas have nowhere to be allocated.
        if cluster_status in ("green", "yellow"):
            return ComponentHealth(status=HealthStatus.OK)
        return ComponentHealth(
            status=HealthStatus.DEGRADED, message=f"cluster status is {cluster_status}"
        )


class NotConfiguredCheck:
    async def check(self) -> ComponentHealth:
        return ComponentHealth(status=HealthStatus.DOWN, message="not set up yet")


def build_health_checks(engine: AsyncEngine, opensearch: AsyncOpenSearch) -> dict[str, HealthCheck]:
    return {
        "postgres": PostgresCheck(engine),
        "opensearch": OpenSearchCheck(opensearch),
        "cape": NotConfiguredCheck(),
        "guest": NotConfiguredCheck(),
    }


async def evaluate(check: HealthCheck, timeout_s: float = DEFAULT_TIMEOUT_S) -> ComponentHealth:
    """Run one check; a failure or a hang becomes `down` instead of an exception."""
    try:
        async with asyncio.timeout(timeout_s):
            return await check.check()
    except TimeoutError:
        return ComponentHealth(status=HealthStatus.DOWN, message=f"timed out after {timeout_s:g}s")
    except Exception as error:  # noqa: BLE001 - any failure of a probe means the component is down
        # Only the type is reported: driver messages can carry hostnames and credentials.
        return ComponentHealth(
            status=HealthStatus.DOWN, message=f"check failed: {type(error).__name__}"
        )


async def collect_health(
    checks: Mapping[str, HealthCheck], timeout_s: float = DEFAULT_TIMEOUT_S
) -> SystemHealth:
    results = await asyncio.gather(*(evaluate(check, timeout_s) for check in checks.values()))
    return SystemHealth.model_validate(dict(zip(checks, results, strict=True)))
