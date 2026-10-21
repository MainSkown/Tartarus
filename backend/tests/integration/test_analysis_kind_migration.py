import asyncio
from collections.abc import AsyncIterator
from pathlib import Path
from uuid import uuid4

import pytest
from alembic.config import Config
from sqlalchemy import inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from alembic import command
from app.config import get_settings

BACKEND_DIR = Path(__file__).resolve().parents[2]
SHA = "a" * 64

pytestmark = pytest.mark.integration

INSERT_SAMPLE = text(
    "INSERT INTO sample (sha256, sha1, md5, size, original_name, stored_path, first_seen)"
    " VALUES (:sha, :sha1, :md5, 1, 'a.exe', '/s/a.zip', now())"
).bindparams(sha=SHA, sha1="b" * 40, md5="c" * 32)
INSERT_OLD_ANALYSIS = text(
    "INSERT INTO analysis (sample_sha256, filename, status, phase, options, detected_families,"
    " event_count, disk_bytes, submitted_at)"
    " VALUES (:sha, 'a.exe', 'done', 'final', '{}', '{}', 0, 0, now()) RETURNING id"
).bindparams(sha=SHA)


@pytest.fixture
async def configured(
    postgres_url: str, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[tuple[AsyncEngine, Config]]:
    admin = create_async_engine(postgres_url, isolation_level="AUTOCOMMIT")
    name = f"kind_{uuid4().hex[:12]}"
    async with admin.connect() as connection:
        await connection.execute(text(f'CREATE DATABASE "{name}"'))
    await admin.dispose()
    url = make_url(postgres_url).set(database=name).render_as_string(hide_password=False)
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.setenv("OPENSEARCH_URL", "http://unused:9200")
    get_settings.cache_clear()
    engine = create_async_engine(url)
    yield engine, Config(str(BACKEND_DIR / "alembic.ini"))
    await engine.dispose()
    get_settings.cache_clear()


async def _kinds(engine: AsyncEngine) -> list[str]:
    async with engine.connect() as connection:
        return list(await connection.scalars(text("SELECT kind FROM analysis ORDER BY id")))


async def test_analyses_from_before_the_kind_read_as_runs_once_migrated(
    configured: tuple[AsyncEngine, Config],
) -> None:
    engine, config = configured
    await asyncio.to_thread(command.upgrade, config, "0007")
    async with engine.begin() as connection:
        await connection.execute(INSERT_SAMPLE)
        await connection.execute(INSERT_OLD_ANALYSIS)

    await asyncio.to_thread(command.upgrade, config, "head")

    assert await _kinds(engine) == ["run"]


async def test_the_migration_matches_the_models(configured: tuple[AsyncEngine, Config]) -> None:
    _, config = configured
    await asyncio.to_thread(command.upgrade, config, "head")

    await asyncio.to_thread(command.check, config)


async def test_downgrading_a_populated_database_drops_the_kind_and_keeps_the_analyses(
    configured: tuple[AsyncEngine, Config],
) -> None:
    engine, config = configured
    await asyncio.to_thread(command.upgrade, config, "head")
    async with engine.begin() as connection:
        await connection.execute(INSERT_SAMPLE)
        await connection.execute(INSERT_OLD_ANALYSIS)
        await connection.execute(text("UPDATE analysis SET kind = 'imported'"))

    await asyncio.to_thread(command.downgrade, config, "0007")

    async with engine.connect() as connection:
        columns = await connection.run_sync(
            lambda sync: [column["name"] for column in inspect(sync).get_columns("analysis")]
        )
        remaining = await connection.scalar(text("SELECT count(*) FROM analysis"))
    assert "kind" not in columns
    assert remaining == 1
