import logging
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager

from fastapi import FastAPI
from opensearchpy import AsyncOpenSearch
from sqlalchemy.ext.asyncio import AsyncEngine

from app.analyses.runner import build_runner
from app.analyses.summary import read_report
from app.api import api_router
from app.api.internal import router as internal_router
from app.api.operation_ids import generate_operation_id
from app.cape.client import CapeClient
from app.cape.control import CapeControl
from app.cape.health import CapeCheck, CapeProbe, GuestCheck
from app.config import Settings, get_settings
from app.db.session import create_engine, create_session_factory
from app.errors import ErrorEnvelope, install_error_handlers
from app.health import HealthCheck, OpenSearchCheck, PostgresCheck
from app.ingest.ingester import ReportIngester
from app.live.hub import LiveHub
from app.live.manager import LiveCollectionManager
from app.logging_config import configure_logging
from app.rules.registry import RuleRegistry
from app.samples.store import SampleStore
from app.search.client import create_opensearch_client
from app.search.index import EventIndex
from app.ws.desktop import router as desktop_ws_router
from app.ws.live import router as live_ws_router
from app.ws.system import router as system_ws_router

logger = logging.getLogger(__name__)


def build_health_checks(
    engine: AsyncEngine, opensearch: AsyncOpenSearch, cape: CapeProbe, guest_label: str
) -> dict[str, HealthCheck]:
    return {
        "postgres": PostgresCheck(engine),
        "opensearch": OpenSearchCheck(opensearch),
        "cape": CapeCheck(cape),
        "guest": GuestCheck(cape, guest_label),
    }


def _build_lifespan(
    settings: Settings | None,
) -> Callable[[FastAPI], AbstractAsyncContextManager[None]]:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        # Resolved here, not in create_app, so importing the module needs no environment.
        resolved = settings or get_settings()
        configure_logging(resolved.log_level)
        engine = create_engine(resolved.database_url)
        opensearch = create_opensearch_client(resolved.opensearch_url)
        cape = CapeClient.from_settings(resolved)
        cape_control = CapeControl.from_settings(resolved)
        app.state.engine = engine
        app.state.session_factory = create_session_factory(engine)
        app.state.opensearch = opensearch
        event_index = EventIndex(opensearch)
        app.state.event_index = event_index
        app.state.cape = cape
        app.state.cape_control = cape_control
        sample_store = SampleStore.from_settings(resolved)
        app.state.sample_store = sample_store
        app.state.health_checks = build_health_checks(
            engine, opensearch, cape, resolved.guest_label
        )
        live_hub = LiveHub()
        live_collection = LiveCollectionManager(
            storage_path=resolved.cape_storage_path,
            poll_interval_s=resolved.live_poll_interval_seconds,
            store=event_index,
            hub=live_hub,
        )
        app.state.live_hub = live_hub
        app.state.live_collection = live_collection
        rule_registry = RuleRegistry(resolved.rules_path, app.state.session_factory)
        app.state.rule_registry = rule_registry
        await rule_registry.start()
        runner = build_runner(
            app.state.session_factory,
            cape,
            sample_store,
            read_report,
            ReportIngester(event_index),
            resolved,
            live_collection,
        )
        app.state.runner = runner
        runner.start()
        logger.info("Backend started (%s)", resolved.environment)
        try:
            yield
        finally:
            await runner.stop()
            await rule_registry.stop()
            await live_collection.aclose()
            await cape.aclose()
            await cape_control.aclose()
            await opensearch.close()
            await engine.dispose()

    return lifespan


def create_app(settings: Settings | None = None) -> FastAPI:
    app = FastAPI(
        title="Tartarus",
        lifespan=_build_lifespan(settings),
        generate_unique_id_function=generate_operation_id,
        responses={"default": {"model": ErrorEnvelope}},
    )
    install_error_handlers(app)
    app.include_router(api_router)
    app.include_router(internal_router)
    app.include_router(system_ws_router)
    app.include_router(desktop_ws_router)
    app.include_router(live_ws_router)
    return app


app = create_app()
