import socket
from collections.abc import AsyncIterator, Iterator
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from testcontainers.community.opensearch import OpenSearchContainer
from testcontainers.community.postgres import PostgresContainer

from app.db.base import Base
from tests.compose_images import compose_image


@pytest.fixture(scope="session")
def postgres_url() -> Iterator[str]:
    with PostgresContainer(compose_image("postgres"), driver=None) as postgres:
        yield postgres.get_connection_url().replace("postgresql://", "postgresql+asyncpg://", 1)


@pytest.fixture(scope="session")
def opensearch_url() -> Iterator[str]:
    # A hosted CI runner's disk is nearly full, which trips OpenSearch's flood-stage watermark and
    # makes it refuse every index creation (403 index_create_block_exception) mid-run.
    container = OpenSearchContainer(compose_image("opensearch")).with_env(
        "cluster.routing.allocation.disk.threshold_enabled", "false"
    )
    with container as opensearch:
        config = opensearch.get_config()
        yield f"http://{config['host']}:{config['port']}"


@pytest.fixture
def closed_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


@pytest.fixture
async def session_factory(postgres_url: str) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """A database of its own, built from the models, so the runner meets real Postgres types."""
    name = f"runner_{uuid4().hex[:12]}"
    admin = create_async_engine(postgres_url, isolation_level="AUTOCOMMIT")
    async with admin.connect() as connection:
        await connection.execute(text(f'CREATE DATABASE "{name}"'))
    await admin.dispose()
    url = make_url(postgres_url).set(database=name).render_as_string(hide_password=False)
    engine = create_async_engine(url)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()
