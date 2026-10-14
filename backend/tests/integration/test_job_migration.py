import asyncio
from collections.abc import AsyncIterator
from pathlib import Path
from uuid import uuid4

import pytest
from alembic.config import Config
from sqlalchemy import inspect, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from alembic import command
from app.config import get_settings
from app.db import analysis_repository
from app.db import job_repository as repository
from app.db.models import Job
from app.db.models.job import JobStatus, JobType
from tests.test_analysis_repository import SHA_A, make_sample, seeded_analysis

BACKEND_DIR = Path(__file__).resolve().parents[2]

pytestmark = pytest.mark.integration


@pytest.fixture
async def migrated_engine(
    postgres_url: str, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[AsyncEngine]:
    admin = create_async_engine(postgres_url, isolation_level="AUTOCOMMIT")
    name = f"jobs_{uuid4().hex[:12]}"
    async with admin.connect() as connection:
        await connection.execute(text(f'CREATE DATABASE "{name}"'))
    await admin.dispose()
    url = make_url(postgres_url).set(database=name).render_as_string(hide_password=False)
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.setenv("OPENSEARCH_URL", "http://unused:9200")
    get_settings.cache_clear()
    engine = create_async_engine(url)
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    # alembic's env.py starts its own event loop, so it runs in a thread.
    await asyncio.to_thread(command.upgrade, config, "head")
    yield engine
    await asyncio.to_thread(command.downgrade, config, "0004")
    async with engine.connect() as connection:
        tables = await connection.run_sync(lambda sync: inspect(sync).get_table_names())
    assert "job" not in tables
    await engine.dispose()
    get_settings.cache_clear()


async def test_the_migration_matches_the_models(migrated_engine: AsyncEngine) -> None:
    config = Config(str(BACKEND_DIR / "alembic.ini"))

    await asyncio.to_thread(command.check, config)


async def test_postgres_cascades_a_deleted_analysis_to_its_jobs(
    migrated_engine: AsyncEngine,
) -> None:
    factory = async_sessionmaker(migrated_engine, expire_on_commit=False)
    async with factory() as session:
        analysis = await seeded_analysis(session)
        await repository.create_job(session, JobType.EXPORT_REPORT, analysis.id)
        kept = await repository.create_job(session, JobType.GUEST_BUILD, None)

        await analysis_repository.delete_analysis(session, analysis.id)

        assert [job.id for job in await session.scalars(select(Job))] == [kept.id]


async def test_a_job_round_trips_its_result_and_progress_on_postgres(
    migrated_engine: AsyncEngine,
) -> None:
    factory = async_sessionmaker(migrated_engine, expire_on_commit=False)
    async with factory() as session:
        job = await repository.create_job(session, JobType.EXPORT_REPORT, None)
        await repository.record_progress(session, job.id, "Rendering", 40)
        await repository.finish_job(session, job.id, JobStatus.DONE, {"file": "7/a.pdf"})

    async with factory() as session:
        stored = await repository.get_job(session, job.id)

    assert stored is not None
    assert (stored.status, stored.progress, stored.result) == (
        JobStatus.DONE,
        100,
        {"file": "7/a.pdf"},
    )


@pytest.mark.parametrize(
    ("column", "value"),
    [("type", "make_coffee"), ("status", "paused"), ("progress", "101"), ("progress", "-1")],
)
async def test_the_database_refuses_a_job_it_does_not_describe(
    migrated_engine: AsyncEngine, column: str, value: str
) -> None:
    values = {"type": "ingest", "status": "pending", "progress": "0", column: value}
    insert = text(
        "INSERT INTO job (type, status, step, progress, log, created_at, updated_at)"
        " VALUES (:type, :status, '', :progress, '', now(), now())"
    ).bindparams(type=values["type"], status=values["status"], progress=int(values["progress"]))

    async with migrated_engine.begin() as connection:
        with pytest.raises(IntegrityError):
            await connection.execute(insert)


async def test_a_job_cannot_point_at_an_analysis_that_does_not_exist(
    migrated_engine: AsyncEngine,
) -> None:
    factory = async_sessionmaker(migrated_engine, expire_on_commit=False)
    async with factory() as session:
        await analysis_repository.add_sample_if_new(session, make_sample(SHA_A))
        with pytest.raises(IntegrityError):
            await repository.create_job(session, JobType.EXPORT_REPORT, 424242)
