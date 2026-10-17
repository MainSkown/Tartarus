import asyncio
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api.dependencies import get_guest_control
from app.api.guests import router as guests_router
from app.api.operation_ids import generate_operation_id
from app.db import analysis_repository as repository
from app.db.base import Base
from app.db.models import Job
from app.db.models.analysis import AnalysisStatus
from app.db.models.job import JobStatus
from app.errors import install_error_handlers
from app.guest.build_job import BuildTracking
from app.guest.http_errors import install_guest_control_error_handler
from app.jobs.runner import JobRunner
from tests.guest.fakes import FakeGuestControl
from tests.test_analysis_repository import seeded_analysis

UNREACHABLE_MESSAGE = "The guest control service is not reachable"


@dataclass
class Harness:
    client: httpx.AsyncClient
    app: FastAPI
    factory: async_sessionmaker[AsyncSession]
    control: FakeGuestControl
    tracking: BuildTracking

    async def set_analysis_status(self, status: AnalysisStatus) -> None:
        async with self.factory() as session:
            created = await seeded_analysis(session)
            await repository.update_analysis(session, created.id, status=status)

    def use(self, control: FakeGuestControl) -> FakeGuestControl:
        self.app.dependency_overrides[get_guest_control] = lambda: control
        self.control = control
        return control


def _enable_foreign_keys(dbapi_connection: object, _record: object) -> None:
    cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


@pytest.fixture
async def harness(
    tmp_path: Path, make_client: Callable[[FastAPI], httpx.AsyncClient]
) -> AsyncIterator[Harness]:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'guests.sqlite3'}")
    event.listen(engine.sync_engine, "connect", _enable_foreign_keys)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    app = FastAPI(generate_unique_id_function=generate_operation_id)
    install_error_handlers(app)
    install_guest_control_error_handler(app)
    app.state.session_factory = factory
    app.include_router(guests_router, prefix="/api")
    # Never started: a submitted job stays `pending`, which is what the API tests look at.
    tracking = BuildTracking(JobRunner(factory, tmp_path / "exports"))
    app.state.build_tracking = tracking
    control = FakeGuestControl()
    app.dependency_overrides[get_guest_control] = lambda: control
    async with make_client(app) as client:
        yield Harness(client, app, factory, control, tracking)
    await engine.dispose()


async def jobs_of(harness: Harness) -> list[Job]:
    async with harness.factory() as session:
        return list(await session.scalars(select(Job)))


async def wait_until_ended(harness: Harness) -> Job:
    async def poll() -> Job:
        while True:
            [job] = await jobs_of(harness)
            if job.status in (JobStatus.DONE, JobStatus.FAILED):
                return job
            await asyncio.sleep(0.005)

    return await asyncio.wait_for(poll(), 5.0)
