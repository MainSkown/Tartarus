"""The report from request to download, through the real job runner and the real handler; only
the views the report is gathered from are replaced.
"""

import asyncio
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api.analyses import router as analyses_router
from app.api.dependencies import (
    get_cape,
    get_cape_storage_path,
    get_event_index,
    get_exports_path,
    get_job_runner,
    get_sample_store,
)
from app.api.export import router as export_router
from app.api.jobs import router as jobs_router
from app.api.operation_ids import generate_operation_id
from app.db import analysis_repository
from app.db.base import Base
from app.db.models.analysis import AnalysisStatus
from app.db.models.job import JobType
from app.errors import install_error_handlers
from app.export.report import job
from app.export.report.assemble import build_report_model
from app.export.report.gather import ReportSources
from app.export.report.model import ReportInclude
from app.jobs.runner import JobRunner
from app.samples.store import SampleStore
from app.views.attack_table import load_attack_table
from tests.export.report.fixtures import SAMPLE_NAME, make_inputs
from tests.test_analysis_repository import _enable_foreign_keys, seeded_analysis

POLL_INTERVAL_S = 0.02
POLL_LIMIT_S = 30


class UnusedCape:
    pass


class FakeIndex:
    async def drop(self, analysis_id: int) -> None:
        pass


@dataclass
class Harness:
    client: httpx.AsyncClient
    factory: async_sessionmaker[AsyncSession]
    exports: Path
    analysis_id: int

    async def export(self, format_: str, **include: bool) -> dict[str, Any]:
        response = await self.client.post(
            f"/api/analyses/{self.analysis_id}/export/report",
            json={"format": format_, "include": include},
        )
        assert response.status_code == 202, response.text
        return await self.finished(response.json()["id"])

    async def finished(self, job_id: int) -> dict[str, Any]:
        async with asyncio.timeout(POLL_LIMIT_S):
            while True:
                body = (await self.client.get(f"/api/jobs/{job_id}")).json()
                if body["status"] not in ("pending", "running"):
                    return body  # type: ignore[no-any-return]
                await asyncio.sleep(POLL_INTERVAL_S)


@pytest.fixture
async def harness(
    tmp_path: Path,
    make_client: Callable[[FastAPI], httpx.AsyncClient],
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[Harness]:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'report-job.sqlite3'}")
    event.listen(engine.sync_engine, "connect", _enable_foreign_keys)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        analysis = await seeded_analysis(session, filename=SAMPLE_NAME)
        await analysis_repository.update_analysis(session, analysis.id, status=AnalysisStatus.DONE)

    async def gather(
        _analysis: object, _sources: ReportSources, include: ReportInclude, progress: Any
    ) -> Any:
        progress("Assembling the report", 95)
        return build_report_model(make_inputs(), include)

    monkeypatch.setattr(job, "gather_report", gather)
    exports = tmp_path / "exports"
    runner = JobRunner(factory, exports)
    runner.register(
        JobType.EXPORT_REPORT,
        job.export_report_handler(factory, object(), tmp_path / "cape", load_attack_table()),  # type: ignore[arg-type]
    )
    await runner.start()

    app = FastAPI(generate_unique_id_function=generate_operation_id)
    install_error_handlers(app)
    app.state.session_factory = factory
    for router in (export_router, jobs_router, analyses_router):
        app.include_router(router, prefix="/api")
    app.dependency_overrides[get_job_runner] = lambda: runner
    app.dependency_overrides[get_exports_path] = lambda: exports
    app.dependency_overrides[get_cape] = UnusedCape
    app.dependency_overrides[get_event_index] = FakeIndex
    app.dependency_overrides[get_cape_storage_path] = lambda: tmp_path / "cape"
    app.dependency_overrides[get_sample_store] = lambda: SampleStore(tmp_path / "samples")
    async with make_client(app) as client:
        yield Harness(client, factory, exports, analysis.id)
    await runner.stop()
    await engine.dispose()


async def test_a_pdf_report_is_made_and_downloaded(harness: Harness) -> None:
    finished = await harness.export("pdf")

    assert finished["status"] == "done"
    assert finished["progress"] == 100
    assert finished["analysis_id"] == harness.analysis_id
    download = await harness.client.get(f"/api/jobs/{finished['id']}/download")
    assert download.status_code == 200
    assert download.content.startswith(b"%PDF-")
    assert download.headers["content-type"] == "application/pdf"
    assert download.headers["content-disposition"] == (
        f'attachment; filename="tartarus-report-{harness.analysis_id}.pdf"'
    )


async def test_an_html_report_is_made_and_downloaded(harness: Harness) -> None:
    finished = await harness.export("html")

    download = await harness.client.get(f"/api/jobs/{finished['id']}/download")
    assert download.status_code == 200
    assert download.headers["content-type"] == "text/html; charset=utf-8"
    assert download.headers["content-disposition"] == (
        f'attachment; filename="tartarus-report-{harness.analysis_id}.html"'
    )
    assert SAMPLE_NAME in download.text


async def test_the_progress_the_job_shows_names_the_steps_it_went_through(
    harness: Harness,
) -> None:
    finished = await harness.export("html")

    log = finished["log"].splitlines()
    assert log[0].endswith("Assembling the report")
    assert log[-1].endswith("Saving the file")
    assert finished["step"] == "Saving the file"


async def test_a_report_that_cannot_be_made_fails_the_job_with_the_reason(
    harness: Harness,
) -> None:
    harness.exports.mkdir(parents=True)
    (harness.exports / str(harness.analysis_id)).write_text("not a directory")

    finished = await harness.export("html")

    assert finished["status"] == "failed"
    assert finished["result"]["error"]
    download = await harness.client.get(f"/api/jobs/{finished['id']}/download")
    assert download.status_code == 409


async def test_a_finished_reports_file_is_gone_once_the_analysis_is_deleted(
    harness: Harness,
) -> None:
    finished = await harness.export("pdf")
    report = harness.exports / finished["result"]["file"]
    assert report.is_file()

    response = await harness.client.delete(f"/api/analyses/{harness.analysis_id}")

    assert response.status_code == 204
    assert not report.exists()
    assert not report.parent.exists()
    assert (await harness.client.get(f"/api/jobs/{finished['id']}")).status_code == 404
