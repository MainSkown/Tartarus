from collections.abc import Mapping

import httpx
from fastapi import FastAPI

from app.api.system import get_health_checks
from app.health import ComponentHealth, HealthCheck, HealthStatus, NotConfiguredCheck


class RaisingCheck:
    async def check(self) -> ComponentHealth:
        raise ConnectionError


class OkCheck:
    async def check(self) -> ComponentHealth:
        return ComponentHealth(status=HealthStatus.OK)


def use_checks(app: FastAPI, checks: Mapping[str, HealthCheck]) -> None:
    app.dependency_overrides[get_health_checks] = lambda: checks


async def test_health_reports_every_component(app: FastAPI, client: httpx.AsyncClient) -> None:
    use_checks(
        app,
        {
            "postgres": OkCheck(),
            "opensearch": OkCheck(),
            "cape": NotConfiguredCheck(),
            "guest": NotConfiguredCheck(),
        },
    )

    response = await client.get("/api/system/health")

    assert response.status_code == 200
    assert response.json() == {
        "postgres": {"status": "ok", "message": None},
        "opensearch": {"status": "ok", "message": None},
        "cape": {"status": "down", "message": "not set up yet"},
        "guest": {"status": "down", "message": "not set up yet"},
    }


async def test_health_answers_200_even_when_everything_is_down(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    use_checks(
        app,
        {
            "postgres": RaisingCheck(),
            "opensearch": RaisingCheck(),
            "cape": NotConfiguredCheck(),
            "guest": NotConfiguredCheck(),
        },
    )

    response = await client.get("/api/system/health")

    assert response.status_code == 200
    statuses = {name: component["status"] for name, component in response.json().items()}
    assert set(statuses.values()) == {"down"}
