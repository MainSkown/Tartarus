import asyncio
from collections.abc import Callable
from pathlib import Path

import httpx
import pytest
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from alembic import command
from app.config import Settings, get_settings
from app.main import create_app

BACKEND_DIR = Path(__file__).resolve().parents[2]

pytestmark = pytest.mark.integration


async def test_health_endpoint_reflects_the_real_stores(
    postgres_url: str,
    opensearch_url: str,
    make_client: Callable[..., httpx.AsyncClient],
) -> None:
    app = create_app(
        Settings(
            database_url=postgres_url, opensearch_url=opensearch_url, environment="development"
        )
    )

    async with app.router.lifespan_context(app), make_client(app) as client:
        response = await client.get("/api/system/health")

    body = response.json()
    assert response.status_code == 200
    assert body["postgres"] == {"status": "ok", "message": None}
    assert body["opensearch"] == {"status": "ok", "message": None}
    assert body["cape"]["status"] == "down"
    assert body["guest"]["status"] == "down"


async def test_alembic_env_migrates_a_real_database(
    postgres_url: str, opensearch_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DATABASE_URL", postgres_url)
    monkeypatch.setenv("OPENSEARCH_URL", opensearch_url)
    get_settings.cache_clear()
    config = Config(str(BACKEND_DIR / "alembic.ini"))

    # alembic's env.py starts its own event loop, so it cannot run inside this one.
    await asyncio.to_thread(command.upgrade, config, "head")

    engine = create_async_engine(postgres_url)
    try:
        async with engine.connect() as connection:
            tables = await connection.execute(
                text("SELECT table_name FROM information_schema.tables WHERE table_schema='public'")
            )
        assert "alembic_version" in {row[0] for row in tables}
    finally:
        await engine.dispose()
        get_settings.cache_clear()
