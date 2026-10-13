from collections.abc import AsyncIterator, Callable
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.analyses.runner import Runner, RunnerConfig
from app.db.base import Base
from tests.analyses.fakes import FakeCape, FakeClock, FakeReports, FakeSamples

CAPE_STORAGE = Path("/cape-storage")
GRACE_SECONDS = 120.0


@pytest.fixture
async def session_factory(tmp_path: Path) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'runner.sqlite3'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


@pytest.fixture
def cape() -> FakeCape:
    return FakeCape()


@pytest.fixture
def samples(tmp_path: Path) -> FakeSamples:
    store = tmp_path / "plain"
    store.mkdir()
    return FakeSamples(store)


@pytest.fixture
def reports() -> FakeReports:
    return FakeReports()


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def config() -> RunnerConfig:
    return RunnerConfig(
        cape_storage_path=CAPE_STORAGE,
        guest_label="win",
        poll_interval=3600.0,
        unreachable_grace=GRACE_SECONDS,
    )


@pytest.fixture
def make_runner(  # noqa: PLR0913, PLR0917 - a fixture assembling every fake
    session_factory: async_sessionmaker[AsyncSession],
    cape: FakeCape,
    samples: FakeSamples,
    reports: FakeReports,
    clock: FakeClock,
    config: RunnerConfig,
) -> Callable[[], Runner]:
    def build() -> Runner:
        return Runner(session_factory, cape, samples, reports, config, clock=clock)

    return build


@pytest.fixture
def runner(make_runner: Callable[[], Runner]) -> Runner:
    return make_runner()
