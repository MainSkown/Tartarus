import logging
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager

from fastapi import FastAPI

from app.api import api_router
from app.api.operation_ids import generate_operation_id
from app.config import Settings, get_settings
from app.db.session import create_engine, create_session_factory
from app.errors import ErrorEnvelope, install_error_handlers
from app.health import build_health_checks
from app.logging_config import configure_logging
from app.search.client import create_opensearch_client

logger = logging.getLogger(__name__)


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
        app.state.engine = engine
        app.state.session_factory = create_session_factory(engine)
        app.state.opensearch = opensearch
        app.state.health_checks = build_health_checks(engine, opensearch)
        logger.info("Backend started (%s)", resolved.environment)
        try:
            yield
        finally:
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
    return app


app = create_app()
