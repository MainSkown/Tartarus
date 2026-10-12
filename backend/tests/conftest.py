from collections.abc import AsyncIterator, Callable

import httpx
import pytest
from fastapi import FastAPI

from app.config import Settings
from app.main import create_app


@pytest.fixture
def settings() -> Settings:
    return Settings(
        database_url="postgresql+asyncpg://user:pw@localhost:5432/db",
        opensearch_url="http://localhost:9200",
        environment="development",
        log_level="info",
    )


@pytest.fixture
def app(settings: Settings) -> FastAPI:
    return create_app(settings)


@pytest.fixture
def make_client() -> Callable[[FastAPI], httpx.AsyncClient]:
    """Builds a client that turns unhandled exceptions into 500 responses like a real server."""

    def build(app: FastAPI) -> httpx.AsyncClient:
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        return httpx.AsyncClient(transport=transport, base_url="http://test")

    return build


@pytest.fixture
async def client(
    app: FastAPI, make_client: Callable[[FastAPI], httpx.AsyncClient]
) -> AsyncIterator[httpx.AsyncClient]:
    async with make_client(app) as http_client:
        yield http_client
