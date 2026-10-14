from types import SimpleNamespace
from typing import cast

import pytest
from fastapi import FastAPI, Request
from opensearchpy import AsyncOpenSearch
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.analyses.runner import Runner
from app.cape.client import CapeClient
from app.cape.control import CapeControl
from app.cape.health import CapeCheck, GuestCheck
from app.db.session import get_session
from app.health import ComponentHealth, HealthStatus, PostgresCheck, evaluate
from app.rules.registry import RuleRegistry
from app.samples.store import SampleStore
from app.search.index import EventIndex


async def test_lifespan_stores_engine_client_and_checks_on_app_state(app: FastAPI) -> None:
    async with app.router.lifespan_context(app):
        assert isinstance(app.state.engine, AsyncEngine)
        assert isinstance(app.state.session_factory, async_sessionmaker)
        assert isinstance(app.state.opensearch, AsyncOpenSearch)
        assert isinstance(app.state.cape, CapeClient)
        assert isinstance(app.state.cape_control, CapeControl)
        assert isinstance(app.state.sample_store, SampleStore)
        assert isinstance(app.state.event_index, EventIndex)
        assert isinstance(app.state.runner, Runner)
        assert isinstance(app.state.rule_registry, RuleRegistry)
        assert set(app.state.health_checks) == {"postgres", "opensearch", "cape", "guest"}
        assert isinstance(app.state.health_checks["postgres"], PostgresCheck)
        assert isinstance(app.state.health_checks["cape"], CapeCheck)
        assert isinstance(app.state.health_checks["guest"], GuestCheck)


async def test_lifespan_starts_without_a_cape_token_and_reports_cape_down(app: FastAPI) -> None:
    async with app.router.lifespan_context(app):
        cape = await evaluate(app.state.health_checks["cape"], timeout_s=1)

    assert cape == ComponentHealth(status=HealthStatus.DOWN, message="CAPE_API_TOKEN is not set")


async def test_lifespan_disposes_engine_and_closes_client_on_shutdown(
    app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    released: list[str] = []

    async def record_dispose(self: AsyncEngine) -> None:
        released.append("engine")

    async def record_close(self: AsyncOpenSearch) -> None:
        released.append("opensearch")

    async def record_cape_close(self: CapeClient) -> None:
        released.append("cape")

    monkeypatch.setattr(AsyncEngine, "dispose", record_dispose)
    monkeypatch.setattr(AsyncOpenSearch, "close", record_close)

    async def record_runner_stop(self: Runner) -> None:
        released.append("runner")

    async def record_control_close(self: CapeControl) -> None:
        released.append("cape_control")

    monkeypatch.setattr(CapeClient, "aclose", record_cape_close)
    monkeypatch.setattr(CapeControl, "aclose", record_control_close)

    stop_registry = RuleRegistry.stop

    async def record_registry_stop(self: RuleRegistry) -> None:
        released.append("rule_registry")
        await stop_registry(self)

    monkeypatch.setattr(Runner, "stop", record_runner_stop)
    monkeypatch.setattr(RuleRegistry, "stop", record_registry_stop)

    async with app.router.lifespan_context(app):
        assert released == []

    assert sorted(released) == [
        "cape",
        "cape_control",
        "engine",
        "opensearch",
        "rule_registry",
        "runner",
    ]
    # A tick in progress still uses the CAPE client and the database, so it must end first.
    assert released.index("runner") < released.index("cape")
    assert released.index("runner") < released.index("engine")
    # A reload in progress writes to the database.
    assert released.index("rule_registry") < released.index("engine")


async def test_session_dependency_yields_a_session_and_closes_it(app: FastAPI) -> None:
    async with app.router.lifespan_context(app):
        sessions = get_session(cast(Request, SimpleNamespace(app=app)))
        session = await anext(sessions)
        assert isinstance(session, AsyncSession)
        with pytest.raises(StopAsyncIteration):
            await anext(sessions)


async def test_the_runner_is_running_while_the_app_is_up(app: FastAPI) -> None:
    async with app.router.lifespan_context(app):
        with pytest.raises(RuntimeError):
            app.state.runner.start()
