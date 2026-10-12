import pytest
from sqlalchemy.ext.asyncio import create_async_engine

from app.health import ComponentHealth, HealthStatus, OpenSearchCheck, PostgresCheck, evaluate
from app.search.client import create_opensearch_client

pytestmark = pytest.mark.integration

ok = ComponentHealth(status=HealthStatus.OK)


async def test_postgres_check_is_ok_against_a_real_database(postgres_url: str) -> None:
    engine = create_async_engine(postgres_url)
    try:
        assert await evaluate(PostgresCheck(engine)) == ok
    finally:
        await engine.dispose()


async def test_postgres_check_is_down_when_the_port_is_closed(closed_port: int) -> None:
    engine = create_async_engine(f"postgresql+asyncpg://u:p@127.0.0.1:{closed_port}/db")
    try:
        result = await evaluate(PostgresCheck(engine))
    finally:
        await engine.dispose()

    assert result.status is HealthStatus.DOWN
    assert result.message


async def test_opensearch_check_is_ok_against_a_real_cluster(opensearch_url: str) -> None:
    client = create_opensearch_client(opensearch_url)
    try:
        assert await evaluate(OpenSearchCheck(client)) == ok
    finally:
        await client.close()


async def test_opensearch_check_is_down_when_the_port_is_closed(closed_port: int) -> None:
    client = create_opensearch_client(f"http://127.0.0.1:{closed_port}")
    try:
        result = await evaluate(OpenSearchCheck(client))
    finally:
        await client.close()

    assert result.status is HealthStatus.DOWN
    assert result.message
