"""A done analysis with its events in a real index, behind the view routers.

Shared by the tests of every view endpoint: the report is the real, trimmed analysis 6, ingested
through the real ingester, so the views are tested on what the product actually indexes.
"""

from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from opensearchpy import AsyncOpenSearch
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.dependencies import get_event_index
from app.api.events import router as events_api_router
from app.api.operation_ids import generate_operation_id
from app.api.query import router as query_router
from app.api.views_events import router as events_router
from app.api.views_findings import router as findings_router
from app.db import analysis_repository as repository
from app.db.models.analysis import AnalysisPhase, AnalysisStatus
from app.errors import install_error_handlers
from app.ingest.ingester import ReportIngester
from app.search.client import create_opensearch_client
from app.search.index import EventIndex
from tests.ingest.conftest import FULL_REPORT
from tests.test_analysis_repository import OPTIONS, SHA_A, make_sample

CAPE_TASK_ID = 6


@dataclass
class ViewStack:
    app: FastAPI
    client: httpx.AsyncClient
    analysis_id: int
    index: EventIndex
    factory: async_sessionmaker[AsyncSession]
    storage_root: Path

    @property
    def analysis_dir(self) -> Path:
        """Where CAPE's files for this analysis would be (`analyses/<task>/`), created empty."""
        path = self.storage_root / "analyses" / str(CAPE_TASK_ID)
        path.mkdir(parents=True, exist_ok=True)
        return path


@pytest.fixture
async def view_stack(
    session_factory: async_sessionmaker[AsyncSession],
    opensearch_url: str,
    make_client: Callable[[FastAPI], httpx.AsyncClient],
    tmp_path: Path,
) -> AsyncIterator[ViewStack]:
    opensearch: AsyncOpenSearch = create_opensearch_client(opensearch_url)
    index = EventIndex(opensearch)
    async with session_factory() as session:
        await repository.add_sample_if_new(session, make_sample())
        created = await repository.create_analysis(
            session, sample_sha256=SHA_A, filename="benign.exe", options=OPTIONS
        )
        await repository.update_analysis(
            session,
            created.id,
            status=AnalysisStatus.DONE,
            phase=AnalysisPhase.FINAL,
            cape_task_id=CAPE_TASK_ID,
        )
    await ReportIngester(index).ingest(created.id, FULL_REPORT)

    app = FastAPI(generate_unique_id_function=generate_operation_id)
    install_error_handlers(app)
    app.state.session_factory = session_factory
    app.include_router(events_router, prefix="/api")
    app.include_router(findings_router, prefix="/api")
    app.include_router(events_api_router, prefix="/api")
    app.include_router(query_router, prefix="/api")
    app.dependency_overrides[get_event_index] = lambda: index
    async with make_client(app) as client:
        yield ViewStack(app, client, created.id, index, session_factory, tmp_path / "storage")
    await index.drop(created.id)
    await opensearch.close()
