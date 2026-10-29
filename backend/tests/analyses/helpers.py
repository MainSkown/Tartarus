from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db import analysis_repository as repository
from app.db.models import Analysis
from app.db.models.analysis import AnalysisStatus
from tests.test_analysis_repository import OPTIONS, SHA_A, make_sample


async def enqueue(
    session_factory: async_sessionmaker[AsyncSession],
    filename: str = "benign.exe",
    sha256: str = SHA_A,
    options: dict[str, object] | None = None,
) -> int:
    async with session_factory() as session:
        await repository.add_sample_if_new(session, make_sample(sha256))
        created = await repository.create_analysis(
            session,
            sample_sha256=sha256,
            filename=filename,
            options={"guest": "win", **(options or OPTIONS)},
        )
        return created.id


async def load(session_factory: async_sessionmaker[AsyncSession], analysis_id: int) -> Analysis:
    async with session_factory() as session:
        analysis = await repository.get_analysis(session, analysis_id)
    assert analysis is not None
    return analysis


async def adopt_by_cape(
    session_factory: async_sessionmaker[AsyncSession],
    task_id: int,
    status: AnalysisStatus = AnalysisStatus.STARTING,
    options: dict[str, object] | None = None,
    **changes: Any,
) -> int:
    """An analysis the runner already submitted to CAPE as `task_id`."""
    analysis_id = await enqueue(session_factory, options=options)
    async with session_factory() as session:
        await repository.update_analysis(
            session, analysis_id, status=status, cape_task_id=task_id, **changes
        )
    return analysis_id


def as_utc(moment: datetime | None) -> datetime | None:
    """SQLite hands timestamps back naive; Postgres keeps the zone."""
    return moment.replace(tzinfo=UTC) if moment is not None and moment.tzinfo is None else moment


# The test database drivers log bound parameters at DEBUG; production sets only the `app` logger's
# level (`configure_logging`), so they never do there.
_DRIVER_LOGGERS = ("aiosqlite", "sqlalchemy")


def app_log_text(caplog: pytest.LogCaptureFixture) -> str:
    """Every captured line, but for the test database drivers' own."""
    return "\n".join(
        record.getMessage() + (record.exc_text or "")
        for record in caplog.records
        if not record.name.startswith(_DRIVER_LOGGERS)
    )
