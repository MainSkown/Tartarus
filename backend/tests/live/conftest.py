import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.base import Base

FIXTURES = Path(__file__).parent.parent / "fixtures" / "cape" / "live_logs_45"
PIDS = (2476, 9708)


@pytest.fixture(scope="session")
def report_processes() -> dict[int, dict[str, Any]]:
    report = json.loads((FIXTURES / "report_calls.json").read_text())
    return {entry["process_id"]: entry for entry in report["behavior"]["processes"]}


@pytest.fixture(scope="session")
def log_bytes() -> dict[int, bytes]:
    return {pid: (FIXTURES / f"{pid}.bson").read_bytes() for pid in PIDS}


@pytest.fixture
async def session_factory(tmp_path: Path) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'live.sqlite3'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()
