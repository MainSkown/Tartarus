import asyncio
from pathlib import Path
from uuid import uuid4

import pytest
from alembic.config import Config
from sqlalchemy import inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import (
    AsyncConnection,
    AsyncEngine,
    async_sessionmaker,
    create_async_engine,
)

from alembic import command
from app.config import get_settings
from app.db import analysis_repository as repository
from app.db.models import Sample
from app.db.models.analysis import AnalysisStatus, Severity

BACKEND_DIR = Path(__file__).resolve().parents[2]
SHA = "f" * 64

pytestmark = pytest.mark.integration


@pytest.fixture
async def empty_database_url(postgres_url: str) -> str:
    """A database of its own per test, so migrations start from nothing."""
    admin = create_async_engine(postgres_url, isolation_level="AUTOCOMMIT")
    name = f"a1_{uuid4().hex[:12]}"
    async with admin.connect() as connection:
        await connection.execute(text(f'CREATE DATABASE "{name}"'))
    await admin.dispose()
    return make_url(postgres_url).set(database=name).render_as_string(hide_password=False)


async def table_names(connection: AsyncConnection) -> set[str]:
    return set(await connection.run_sync(lambda sync: inspect(sync).get_table_names()))


async def test_migration_0002_adds_the_tables_and_the_repository_works_on_postgres(
    empty_database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DATABASE_URL", empty_database_url)
    monkeypatch.setenv("OPENSEARCH_URL", "http://unused:9200")
    get_settings.cache_clear()
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    engine = create_async_engine(empty_database_url)
    try:
        # alembic's env.py starts its own event loop, so it runs in a thread.
        await asyncio.to_thread(command.upgrade, config, "0001")
        async with engine.connect() as connection:
            assert "analysis" not in await table_names(connection)

        await asyncio.to_thread(command.upgrade, config, "head")
        await asyncio.to_thread(command.check, config)
        async with engine.connect() as connection:
            assert {"sample", "analysis"} <= await table_names(connection)

        await exercise_repository(engine)

        await asyncio.to_thread(command.downgrade, config, "0001")
        async with engine.connect() as connection:
            tables = await table_names(connection)
        assert "analysis" not in tables
        assert "sample" not in tables
        assert "setting" in tables
    finally:
        await engine.dispose()
        get_settings.cache_clear()


async def exercise_repository(engine: AsyncEngine) -> None:
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        await repository.add_sample_if_new(
            session,
            Sample(
                sha256=SHA,
                sha1="1" * 40,
                md5="2" * 32,
                size=4096,
                original_name="benign.exe",
                stored_path=f"/data/samples/{SHA}.zip",
            ),
        )
        created = await repository.create_analysis(
            session, sample_sha256=SHA, filename="benign.exe", options={"route": "inetsim"}
        )
        await repository.update_analysis(
            session,
            created.id,
            status=AnalysisStatus.DONE,
            score=7.5,
            max_severity=Severity.HIGH,
            summary={"signatures": [{"name": "persistence", "severity": 3}]},
        )

    async with session_factory() as session:
        reloaded = await repository.get_analysis(session, created.id)
        assert reloaded is not None
        assert reloaded.status is AnalysisStatus.DONE
        assert reloaded.score == 7.5
        assert reloaded.max_severity is Severity.HIGH
        assert reloaded.summary == {"signatures": [{"name": "persistence", "severity": 3}]}
        waiting = [
            await repository.create_analysis(
                session, sample_sha256=SHA, filename=f"queued{n}.exe", options={}
            )
            for n in range(2)
        ]
        assert await repository.queue_positions(session, [row.id for row in waiting]) == {
            waiting[0].id: 1,
            waiting[1].id: 2,
        }
        assert await repository.queue_positions(session, [created.id]) == {}
        for row in waiting:
            assert await repository.delete_analysis(session, row.id) is True
        assert await repository.delete_analysis(session, created.id) is True
        assert await repository.delete_sample_if_unreferenced(session, SHA) is True
