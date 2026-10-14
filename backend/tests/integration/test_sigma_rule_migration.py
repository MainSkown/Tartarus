import asyncio
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from alembic.config import Config
from fastapi import FastAPI
from sqlalchemy import inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from alembic import command
from app.config import Settings, get_settings
from app.db import rule_repository as repository
from app.main import create_app
from app.rules.rule import Validity
from tests.rules.rule_factory import make_rule
from tests.rules.support import rule_yaml, simple_detection

BACKEND_DIR = Path(__file__).resolve().parents[2]
FIRST = "11111111-1111-4111-8111-111111111111"
SECOND = "22222222-2222-4222-8222-222222222222"

pytestmark = pytest.mark.integration


@pytest.fixture
async def migrated_engine(
    postgres_url: str, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[AsyncEngine]:
    admin = create_async_engine(postgres_url, isolation_level="AUTOCOMMIT")
    name = f"rules_{uuid4().hex[:12]}"
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
    await asyncio.to_thread(command.downgrade, config, "0002")
    async with engine.connect() as connection:
        tables = await connection.run_sync(lambda sync: inspect(sync).get_table_names())
    assert "sigma_rule" not in tables
    await engine.dispose()
    get_settings.cache_clear()


async def test_the_migration_matches_the_model(migrated_engine: AsyncEngine) -> None:
    config = Config(str(BACKEND_DIR / "alembic.ini"))

    await asyncio.to_thread(command.check, config)


async def test_the_repository_syncs_toggles_and_deletes_on_postgres(
    migrated_engine: AsyncEngine,
) -> None:
    factory = async_sessionmaker(migrated_engine, expire_on_commit=False)
    async with factory() as session:
        await repository.sync_rules(
            session,
            [make_rule(FIRST), make_rule(SECOND, validity=Validity.UNSUPPORTED, error="no")],
        )
        await repository.set_enabled(session, FIRST, False)

    async with factory() as session:
        flags = await repository.sync_rules(session, [make_rule(FIRST, title="Edited")])
        stored = await repository.list_rules(session)

    assert flags == {FIRST: False}
    assert [(row.id, row.title, row.enabled) for row in stored] == [(FIRST, "Edited", False)]


async def test_the_database_refuses_a_validity_the_engine_does_not_know(
    migrated_engine: AsyncEngine,
) -> None:
    insert = text(
        "INSERT INTO sigma_rule (id, title, path, content_sha256, validity, loaded_at)"
        " VALUES ('x', 't', 'p', 'h', 'maybe', now())"
    )

    async with migrated_engine.begin() as connection:
        with pytest.raises(IntegrityError):
            await connection.execute(insert)


async def test_the_app_lists_rules_and_keeps_a_toggle_across_a_restart(
    migrated_engine: AsyncEngine,
    opensearch_url: str,
    make_client: Callable[[FastAPI], httpx.AsyncClient],
    tmp_path: Path,
) -> None:
    rules_dir = tmp_path / "sigma"
    (rules_dir / "custom").mkdir(parents=True)
    (rules_dir / "custom" / "whoami.yml").write_text(
        rule_yaml(simple_detection("Image|endswith: '\\cmd.exe'"), rule_id=FIRST), encoding="utf-8"
    )
    settings = Settings(
        database_url=migrated_engine.url.render_as_string(hide_password=False),
        opensearch_url=opensearch_url,
        rules_path=rules_dir,
    )

    first_run = create_app(settings)
    async with first_run.router.lifespan_context(first_run), make_client(first_run) as client:
        listed = (await client.get("/api/rules")).json()
        patched = await client.patch(f"/api/rules/{FIRST}", json={"enabled": False})
    assert [(rule["id"], rule["enabled"], rule["validity"]) for rule in listed] == [
        (FIRST, True, "valid")
    ]
    assert patched.status_code == 200

    second_run = create_app(settings)
    async with second_run.router.lifespan_context(second_run), make_client(second_run) as client:
        relisted = (await client.get("/api/rules")).json()
        assert second_run.state.rule_registry.active_rules() == []
    assert [(rule["id"], rule["enabled"]) for rule in relisted] == [(FIRST, False)]
