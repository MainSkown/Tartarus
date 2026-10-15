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
from app.cape.health import CapeCheck, CapeProbe
from app.config import Settings, get_settings
from app.db.models.job import JobType
from app.db.session import create_engine, create_session_factory
from app.errors import ErrorEnvelope, install_error_handlers
from app.export.report.job import export_report_handler
from app.guest.build_job import BuildTracking, guest_build_handler, reattach_guest_builds
from app.guest.client import GuestControl, HttpGuestControl
from app.guest.health import GuestCheck
from app.guest.http_errors import install_guest_control_error_handler
from app.guest.selftest import NoSelfTest
from app.health import HealthCheck, OpenSearchCheck, PostgresCheck
from app.ingest.ingester import ReportIngester
from app.jobs.runner import JobRunner
from app.live.hub import LiveHub
from app.live.manager import LiveCollectionManager
from app.logging_config import configure_logging
from app.rules.registry import RuleRegistry
from app.samples.store import SampleStore
from app.search.client import create_opensearch_client
from app.search.index import EventIndex
from app.views.attack_table import load_attack_table
from app.ws.desktop import router as desktop_ws_router
from app.ws.live import router as live_ws_router
from app.ws.system import router as system_ws_router

logger = logging.getLogger(__name__)


def build_health_checks(
    engine: AsyncEngine, opensearch: AsyncOpenSearch, cape: CapeProbe, guest_control: GuestControl
) -> dict[str, HealthCheck]:
    return {
        "postgres": PostgresCheck(engine),
        "opensearch": OpenSearchCheck(opensearch),
        "cape": CapeCheck(cape),
        "guest": GuestCheck(guest_control),
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
        guest_control = HttpGuestControl.from_settings(resolved)
        app.state.engine = engine
        app.state.session_factory = create_session_factory(engine)
        app.state.opensearch = opensearch
        event_index = EventIndex(opensearch)
        app.state.event_index = event_index
        app.state.cape = cape
        app.state.guest_control = guest_control
        sample_store = SampleStore.from_settings(resolved)
        app.state.sample_store = sample_store
        app.state.health_checks = build_health_checks(engine, opensearch, cape, guest_control)
        rule_registry = RuleRegistry(resolved.rules_path, app.state.session_factory)
        app.state.rule_registry = rule_registry
        live_hub = LiveHub()
        live_collection = LiveCollectionManager(
            storage_path=resolved.cape_storage_path,
            poll_interval_s=resolved.live_poll_interval_seconds,
            store=event_index,
            hub=live_hub,
            rules=rule_registry.active_rules,
        )
        app.state.live_hub = live_hub
        app.state.live_collection = live_collection
        await rule_registry.start()
        runner = build_runner(
            app.state.session_factory,
            cape,
            sample_store,
            read_report,
            ReportIngester(event_index, rules=rule_registry.active_rules),
            guest_control,
            resolved,
            live_collection,
        )
        app.state.runner = runner
        runner.start()
        job_runner = JobRunner(app.state.session_factory, resolved.exports_path)
        job_runner.register(
            JobType.EXPORT_REPORT,
            export_report_handler(
                app.state.session_factory,
                event_index,
                resolved.cape_storage_path,
                load_attack_table(),
            ),
        )
        build_tracking = BuildTracking(job_runner)
        job_runner.register(
            JobType.GUEST_BUILD, guest_build_handler(guest_control, build_tracking, NoSelfTest())
        )
        app.state.job_runner = job_runner
        app.state.build_tracking = build_tracking
        await job_runner.start()
        await reattach_guest_builds(guest_control, build_tracking)
        logger.info("Backend started (%s)", resolved.environment)
        try:
            yield
        finally:
            await job_runner.stop()
            await runner.stop()
            await rule_registry.stop()
            await live_collection.aclose()
            await cape.aclose()
            await guest_control.aclose()
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
    install_guest_control_error_handler(app)
    app.include_router(api_router)
    app.include_router(internal_router)
    app.include_router(system_ws_router)
    app.include_router(desktop_ws_router)
    app.include_router(live_ws_router)
    return app


app = create_app()
