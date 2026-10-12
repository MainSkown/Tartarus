import socket
from collections.abc import Iterator

import pytest
from testcontainers.community.opensearch import OpenSearchContainer
from testcontainers.community.postgres import PostgresContainer

from tests.compose_images import compose_image


@pytest.fixture(scope="session")
def postgres_url() -> Iterator[str]:
    with PostgresContainer(compose_image("postgres"), driver=None) as postgres:
        yield postgres.get_connection_url().replace("postgresql://", "postgresql+asyncpg://", 1)


@pytest.fixture(scope="session")
def opensearch_url() -> Iterator[str]:
    with OpenSearchContainer(compose_image("opensearch")) as opensearch:
        config = opensearch.get_config()
        yield f"http://{config['host']}:{config['port']}"


@pytest.fixture
def closed_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])
