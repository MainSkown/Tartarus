from collections.abc import AsyncIterator
from datetime import timedelta
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db import analysis_repository as repository
from app.db.base import Base, utc_now
from app.db.models.analysis import AnalysisStatus
from app.db.session import get_session
from tests.test_analysis_repository import OPTIONS, SHA_A, make_sample


@pytest.fixture
async def sessions(tmp_path: Path) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'queue.sqlite3'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


def use_sessions(app: FastAPI, sessions: async_sessionmaker[AsyncSession]) -> None:
    async def session_per_request() -> AsyncIterator[AsyncSession]:
        async with sessions() as session:
            yield session

    app.dependency_overrides[get_session] = session_per_request


async def add_analysis(
    session: AsyncSession, filename: str, guest: str, status: AnalysisStatus, started_s_ago: int
) -> int:
    analysis = await repository.create_analysis(
        session, sample_sha256=SHA_A, filename=filename, options={**OPTIONS, "guest": guest}
    )
    changes: dict[str, object] = {"status": status}
    if started_s_ago:
        changes["started_at"] = utc_now() - timedelta(seconds=started_s_ago)
    await repository.update_analysis(session, analysis.id, **changes)  # type: ignore[arg-type]
    return analysis.id


async def seed_two_running_and_one_queued(
    sessions: async_sessionmaker[AsyncSession],
) -> dict[str, int]:
    async with sessions() as session:
        await repository.add_sample_if_new(session, make_sample(SHA_A))
        return {
            "first": await add_analysis(session, "first.exe", "lab3", AnalysisStatus.RUNNING, 90),
            "second": await add_analysis(session, "second.exe", "lab4", AnalysisStatus.RUNNING, 30),
            "third": await add_analysis(session, "third.exe", "lab3", AnalysisStatus.QUEUED, 0),
            "finished": await add_analysis(session, "old.exe", "lab4", AnalysisStatus.DONE, 500),
        }


async def test_the_queue_lists_running_analyses_and_the_place_of_queued_ones(
    app: FastAPI, client: httpx.AsyncClient, sessions: async_sessionmaker[AsyncSession]
) -> None:
    ids = await seed_two_running_and_one_queued(sessions)
    use_sessions(app, sessions)

    response = await client.get("/api/system/queue")

    assert response.status_code == 200
    body = response.json()
    assert [
        (item["id"], item["filename"], item["guest"], item["status"]) for item in body["running"]
    ] == [
        (ids["first"], "first.exe", "lab3", "running"),
        (ids["second"], "second.exe", "lab4", "running"),
    ]
    assert 89 <= body["running"][0]["elapsed_s"] <= 120
    assert body["running"][0]["started_at"] is not None
    assert body["queued_count"] == 1
    assert body["queued"] == [
        {"id": ids["third"], "filename": "third.exe", "guest": "lab3", "position": 1}
    ]


async def test_an_idle_system_has_an_empty_queue(
    app: FastAPI, client: httpx.AsyncClient, sessions: async_sessionmaker[AsyncSession]
) -> None:
    use_sessions(app, sessions)

    response = await client.get("/api/system/queue")

    assert response.status_code == 200
    assert response.json() == {"running": [], "queued_count": 0, "queued": []}


def test_the_queue_is_documented_with_its_operation_id(app: FastAPI) -> None:
    operation = app.openapi()["paths"]["/api/system/queue"]["get"]

    assert operation["operationId"] == "system_queue"
