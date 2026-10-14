from collections.abc import AsyncIterator, Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api.dependencies import get_job_runner
from app.api.export import router as export_router
from app.api.operation_ids import generate_operation_id
from app.db import analysis_repository, job_repository
from app.db.base import Base
from app.db.models import Job
from app.db.models.analysis import AnalysisStatus
from app.db.models.job import JobType
from app.errors import install_error_handlers
from tests.test_analysis_repository import seeded_analysis


@dataclass
class FakeJobRunner:
    factory: async_sessionmaker[AsyncSession]
    submitted: list[tuple[JobType, int | None, Mapping[str, Any]]] = field(default_factory=list)

    async def submit(
        self, job_type: JobType, analysis_id: int | None, params: Mapping[str, Any]
    ) -> Job:
        self.submitted.append((job_type, analysis_id, params))
        async with self.factory() as session:
            return await job_repository.create_job(session, job_type, analysis_id)


@dataclass
class Harness:
    client: httpx.AsyncClient
    runner: FakeJobRunner
    factory: async_sessionmaker[AsyncSession]
    analysis_id: int

    async def set_status(self, status: AnalysisStatus) -> None:
        async with self.factory() as session:
            await analysis_repository.update_analysis(session, self.analysis_id, status=status)

    def request(self, body: Any, analysis_id: int | None = None) -> Any:
        target = self.analysis_id if analysis_id is None else analysis_id
        return self.client.post(f"/api/analyses/{target}/export/report", json=body)


@pytest.fixture
async def harness(
    tmp_path: Path, make_client: Callable[[FastAPI], httpx.AsyncClient]
) -> AsyncIterator[Harness]:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'report-endpoint.sqlite3'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        analysis = await seeded_analysis(session)
        await analysis_repository.update_analysis(session, analysis.id, status=AnalysisStatus.DONE)
    runner = FakeJobRunner(factory)
    app = FastAPI(generate_unique_id_function=generate_operation_id)
    install_error_handlers(app)
    app.state.session_factory = factory
    app.include_router(export_router, prefix="/api")
    app.dependency_overrides[get_job_runner] = lambda: runner
    async with make_client(app) as client:
        yield Harness(client, runner, factory, analysis.id)
    await engine.dispose()


async def test_a_report_request_answers_202_with_the_pending_job(harness: Harness) -> None:
    response = await harness.request({"format": "pdf"})

    assert response.status_code == 202
    body = response.json()
    assert (body["type"], body["status"], body["analysis_id"]) == (
        "export_report",
        "pending",
        harness.analysis_id,
    )
    assert body.keys() >= {"id", "step", "progress", "log", "result", "created_at"}


async def test_the_job_is_submitted_for_the_analysis_with_every_include_option_spelled_out(
    harness: Harness,
) -> None:
    await harness.request({"format": "html", "include": {"notes": False, "raw_iocs": False}})

    assert harness.runner.submitted == [
        (
            JobType.EXPORT_REPORT,
            harness.analysis_id,
            {"format": "html", "include": {"notes": False, "screenshots": True, "raw_iocs": False}},
        )
    ]


async def test_everything_is_included_unless_the_request_leaves_it_out(harness: Harness) -> None:
    await harness.request({"format": "pdf"})

    [(_type, _analysis, params)] = harness.runner.submitted
    assert params["include"] == {"notes": True, "screenshots": True, "raw_iocs": True}


async def test_a_report_of_an_unknown_analysis_is_a_404(harness: Harness) -> None:
    response = await harness.request({"format": "pdf"}, analysis_id=999)

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"
    assert harness.runner.submitted == []


@pytest.mark.parametrize(
    "status", [AnalysisStatus.QUEUED, AnalysisStatus.RUNNING, AnalysisStatus.REPORT_FAILED]
)
async def test_a_report_of_an_analysis_that_is_not_done_is_a_409_that_says_so(
    harness: Harness, status: AnalysisStatus
) -> None:
    await harness.set_status(status)

    response = await harness.request({"format": "pdf"})

    assert response.status_code == 409
    message = response.json()["error"]["message"]
    assert "finished analyses" in message
    assert status.value in message
    assert harness.runner.submitted == []


@pytest.mark.parametrize(
    "body",
    [{"format": "docx"}, {}, {"format": "pdf", "include": {"notes": "perhaps"}}],
    ids=["bad-format", "no-format", "bad-include"],
)
async def test_a_malformed_request_is_a_422_and_submits_nothing(
    harness: Harness, body: dict[str, Any]
) -> None:
    response = await harness.request(body)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
    assert harness.runner.submitted == []


async def test_a_bad_format_is_reported_before_the_analysis_state(harness: Harness) -> None:
    await harness.set_status(AnalysisStatus.RUNNING)

    response = await harness.request({"format": "docx"})

    assert response.status_code == 422


def test_the_operation_is_export_report_and_the_body_names_its_options(app: FastAPI) -> None:
    schema = app.openapi()
    operation = schema["paths"]["/api/analyses/{analysis_id}/export/report"]["post"]

    assert operation["operationId"] == "export_report"
    assert operation["responses"]["202"]
    assert operation["description"]
