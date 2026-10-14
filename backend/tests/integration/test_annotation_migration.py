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
from app.annotations.validation import Target
from app.config import get_settings
from app.db import analysis_repository
from app.db import annotation_repository as repository
from app.db.models import Note
from app.db.models.annotation import TargetType
from tests.test_analysis_repository import SHA_A, make_sample, seeded_analysis

BACKEND_DIR = Path(__file__).resolve().parents[2]
ANNOTATION_TABLES = {"tag", "tag_link", "note"}

pytestmark = pytest.mark.integration


@pytest.fixture
async def migrated_engine(
    postgres_url: str, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[AsyncEngine]:
    admin = create_async_engine(postgres_url, isolation_level="AUTOCOMMIT")
    name = f"annotations_{uuid4().hex[:12]}"
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
    await asyncio.to_thread(command.downgrade, config, "0003")
    async with engine.connect() as connection:
        tables = await connection.run_sync(lambda sync: inspect(sync).get_table_names())
    assert not ANNOTATION_TABLES & set(tables)
    await engine.dispose()
    get_settings.cache_clear()


async def test_the_migration_matches_the_models(migrated_engine: AsyncEngine) -> None:
    config = Config(str(BACKEND_DIR / "alembic.ini"))

    await asyncio.to_thread(command.check, config)


async def test_postgres_cascades_a_deleted_analysis_to_its_annotations(
    migrated_engine: AsyncEngine,
) -> None:
    factory = async_sessionmaker(migrated_engine, expire_on_commit=False)
    async with factory() as session:
        analysis = await seeded_analysis(session)
        await repository.add_tag(session, analysis.id, Target(TargetType.EVENT, "e1"), "c2")
        await repository.add_note(session, analysis.id, Target(TargetType.ANALYSIS), "overall")

        await analysis_repository.delete_analysis(session, analysis.id)

        assert await repository.tag_usage(session) == []
        assert list(await session.scalars(select(Note))) == []


async def test_the_database_refuses_a_target_type_it_does_not_know(
    migrated_engine: AsyncEngine,
) -> None:
    factory = async_sessionmaker(migrated_engine, expire_on_commit=False)
    async with factory() as session:
        await analysis_repository.add_sample_if_new(session, make_sample(SHA_A))
        analysis = await analysis_repository.create_analysis(
            session, sample_sha256=SHA_A, filename="a.exe", options={}
        )
    insert = text(
        "INSERT INTO note (analysis_id, target_type, target_ref, body, created_at, updated_at)"
        " VALUES (:analysis_id, 'file', '', 'x', now(), now())"
    ).bindparams(analysis_id=analysis.id)

    async with migrated_engine.begin() as connection:
        with pytest.raises(IntegrityError):
            await connection.execute(insert)
