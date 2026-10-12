from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from app.api.operation_ids import generate_operation_id
from app.api.settings import router as settings_router
from app.db.base import Base
from app.db.models import Setting  # noqa: F401  # registers the table on Base.metadata
from app.errors import install_error_handlers

DEFAULTS = {
    "default_route": "inetsim",
    "default_timeout": 180,
    "default_interactive": True,
    "disk_warn_gb": 50,
    "disk_block_gb": 20,
}

VALID_BODY: dict[str, Any] = {
    "default_route": "tor",
    "default_timeout": 600,
    "default_interactive": False,
    "disk_warn_gb": 100,
    "disk_block_gb": 10,
}


@pytest.fixture
def database_path(tmp_path: Path) -> Path:
    return tmp_path / "settings.sqlite3"


@pytest.fixture
async def engine(database_path: Path) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(f"sqlite+aiosqlite:///{database_path}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


def build_app(engine: AsyncEngine) -> FastAPI:
    app = FastAPI(generate_unique_id_function=generate_operation_id)
    install_error_handlers(app)
    app.state.session_factory = async_sessionmaker(engine, expire_on_commit=False)
    app.include_router(settings_router, prefix="/api")
    return app


@pytest.fixture
def settings_app(engine: AsyncEngine) -> FastAPI:
    return build_app(engine)


@pytest.fixture
def settings_client(
    settings_app: FastAPI, make_client: Callable[[FastAPI], httpx.AsyncClient]
) -> httpx.AsyncClient:
    return make_client(settings_app)


def rejected_locations(response: httpx.Response) -> list[list[object]]:
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
    fields = response.json()["error"]["details"]["fields"]
    return [field["location"] for field in fields]


async def test_get_on_an_empty_database_returns_the_defaults(
    settings_client: httpx.AsyncClient,
) -> None:
    response = await settings_client.get("/api/settings")

    assert response.status_code == 200
    assert response.json() == DEFAULTS


async def test_put_then_get_in_a_new_session_returns_the_stored_values(
    engine: AsyncEngine,
    database_path: Path,
    settings_client: httpx.AsyncClient,
) -> None:
    put = await settings_client.put("/api/settings", json=VALID_BODY)
    assert put.status_code == 200

    await engine.dispose()
    reopened = create_async_engine(f"sqlite+aiosqlite:///{database_path}")
    try:
        async with make_reopened_client(reopened) as fresh_client:
            response = await fresh_client.get("/api/settings")
    finally:
        await reopened.dispose()

    assert response.json() == VALID_BODY


def make_reopened_client(engine: AsyncEngine) -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=build_app(engine), raise_app_exceptions=False)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


async def test_put_with_a_valid_body_round_trips_every_field(
    settings_client: httpx.AsyncClient,
) -> None:
    put = await settings_client.put("/api/settings", json=VALID_BODY)
    get = await settings_client.get("/api/settings")

    assert put.json() == VALID_BODY
    assert get.json() == VALID_BODY


async def test_put_replaces_all_previously_stored_values(
    settings_client: httpx.AsyncClient,
) -> None:
    await settings_client.put("/api/settings", json=VALID_BODY)
    await settings_client.put("/api/settings", json=DEFAULTS)

    response = await settings_client.get("/api/settings")

    assert response.json() == DEFAULTS


@pytest.mark.parametrize("route", ["sneaky", "INETSIM", ""])
async def test_put_with_an_unknown_route_is_rejected_naming_default_route(
    settings_client: httpx.AsyncClient, route: str
) -> None:
    response = await settings_client.put(
        "/api/settings", json={**VALID_BODY, "default_route": route}
    )

    assert ["body", "default_route"] in rejected_locations(response)


@pytest.mark.parametrize("out_of_range", [59, 1201])
async def test_put_with_a_timeout_outside_60_to_1200_is_rejected_naming_default_timeout(
    settings_client: httpx.AsyncClient, out_of_range: int
) -> None:
    response = await settings_client.put(
        "/api/settings", json={**VALID_BODY, "default_timeout": out_of_range}
    )

    assert ["body", "default_timeout"] in rejected_locations(response)


@pytest.mark.parametrize("field", ["disk_warn_gb", "disk_block_gb"])
@pytest.mark.parametrize("value", [0, -5])
async def test_put_with_a_non_positive_threshold_is_rejected_naming_that_field(
    settings_client: httpx.AsyncClient, field: str, value: int
) -> None:
    response = await settings_client.put("/api/settings", json={**VALID_BODY, field: value})

    assert ["body", field] in rejected_locations(response)


async def test_put_with_warn_equal_to_block_is_rejected_naming_disk_warn_gb(
    settings_client: httpx.AsyncClient,
) -> None:
    response = await settings_client.put(
        "/api/settings", json={**VALID_BODY, "disk_warn_gb": 20, "disk_block_gb": 20}
    )

    assert ["body", "disk_warn_gb"] in rejected_locations(response)


async def test_put_with_warn_below_block_is_rejected_naming_disk_warn_gb(
    settings_client: httpx.AsyncClient,
) -> None:
    response = await settings_client.put(
        "/api/settings", json={**VALID_BODY, "disk_warn_gb": 5, "disk_block_gb": 10}
    )

    assert ["body", "disk_warn_gb"] in rejected_locations(response)


async def test_rejected_put_stores_nothing(settings_client: httpx.AsyncClient) -> None:
    await settings_client.put("/api/settings", json={**VALID_BODY, "default_route": "sneaky"})

    response = await settings_client.get("/api/settings")

    assert response.json() == DEFAULTS


def test_settings_operation_ids_are_tag_and_function_name() -> None:
    app = build_app_without_state()

    operation_ids = {
        (method, path): operation["operationId"]
        for path, operations in app.openapi()["paths"].items()
        for method, operation in operations.items()
        if method in {"get", "put"}
    }

    assert operation_ids == {
        ("get", "/api/settings"): "settings_read",
        ("put", "/api/settings"): "settings_replace",
    }


def build_app_without_state() -> FastAPI:
    app = FastAPI(generate_unique_id_function=generate_operation_id)
    app.include_router(settings_router, prefix="/api")
    return app
