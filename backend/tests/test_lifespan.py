from types import SimpleNamespace
from typing import cast

import pytest
from fastapi import FastAPI, Request
from opensearchpy import AsyncOpenSearch
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.db.session import get_session
from app.health import PostgresCheck


async def test_lifespan_stores_engine_client_and_checks_on_app_state(app: FastAPI) -> None:
    async with app.router.lifespan_context(app):
        assert isinstance(app.state.engine, AsyncEngine)
        assert isinstance(app.state.session_factory, async_sessionmaker)
        assert isinstance(app.state.opensearch, AsyncOpenSearch)
        assert set(app.state.health_checks) == {"postgres", "opensearch", "cape", "guest"}
        assert isinstance(app.state.health_checks["postgres"], PostgresCheck)


async def test_lifespan_disposes_engine_and_closes_client_on_shutdown(
    app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    released: list[str] = []

    async def record_dispose(self: AsyncEngine) -> None:
        released.append("engine")

    async def record_close(self: AsyncOpenSearch) -> None:
        released.append("opensearch")

    monkeypatch.setattr(AsyncEngine, "dispose", record_dispose)
    monkeypatch.setattr(AsyncOpenSearch, "close", record_close)

    async with app.router.lifespan_context(app):
        assert released == []

    assert sorted(released) == ["engine", "opensearch"]


async def test_session_dependency_yields_a_session_and_closes_it(app: FastAPI) -> None:
    async with app.router.lifespan_context(app):
        sessions = get_session(cast(Request, SimpleNamespace(app=app)))
        session = await anext(sessions)
        assert isinstance(session, AsyncSession)
        with pytest.raises(StopAsyncIteration):
            await anext(sessions)
