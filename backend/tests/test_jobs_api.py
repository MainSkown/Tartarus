from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api.dependencies import get_exports_path
from app.api.jobs import router as jobs_router
from app.api.operation_ids import generate_operation_id
from app.db import job_repository
from app.db.base import Base
from app.db.models.job import JobStatus, JobType
from app.errors import install_error_handlers


@dataclass
class Harness:
    client: httpx.AsyncClient
    factory: async_sessionmaker[AsyncSession]
    exports: Path

    async def job(self, status: JobStatus, result: dict[str, Any] | None = None) -> int:
        async with self.factory() as session:
            job = await job_repository.create_job(session, JobType.EXPORT_REPORT, None)
            if status is not JobStatus.PENDING:
                await job_repository.finish_job(session, job.id, status, result or {})
        return job.id

    def export_file(self, relative: str, content: bytes = b"%PDF-1.7 report") -> None:
        target = self.exports / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)

    async def download(self, job_id: int) -> httpx.Response:
        return await self.client.get(f"/api/jobs/{job_id}/download")


@pytest.fixture
async def harness(
    tmp_path: Path, make_client: Callable[[FastAPI], httpx.AsyncClient]
) -> AsyncIterator[Harness]:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'jobs-api.sqlite3'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    exports = tmp_path / "exports"
    exports.mkdir()

    app = FastAPI(generate_unique_id_function=generate_operation_id)
    install_error_handlers(app)
    app.state.session_factory = factory
    app.include_router(jobs_router, prefix="/api")
    app.dependency_overrides[get_exports_path] = lambda: exports

    async with make_client(app) as client:
        yield Harness(client, factory, exports)
    await engine.dispose()


def finished_with_file(relative: str, filename: str = "tartarus-7.pdf") -> dict[str, Any]:
    return {"file": relative, "filename": filename, "media_type": "application/pdf"}


async def test_a_job_is_read_with_its_status_progress_and_log(harness: Harness) -> None:
    async with harness.factory() as session:
        job = await job_repository.create_job(session, JobType.EXPORT_REPORT, None)
        await job_repository.record_progress(session, job.id, "Rendering", 40)

    response = await harness.client.get(f"/api/jobs/{job.id}")

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == job.id
    assert (body["type"], body["status"], body["step"], body["progress"]) == (
        "export_report",
        "pending",
        "Rendering",
        40,
    )
    assert body["log"] == "40% Rendering"
    assert body.keys() >= {"analysis_id", "result", "created_at", "updated_at"}


async def test_an_unknown_job_is_a_404_in_the_error_envelope(harness: Harness) -> None:
    response = await harness.client.get("/api/jobs/999")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


async def test_a_finished_job_downloads_its_file_under_the_name_it_chose(
    harness: Harness,
) -> None:
    harness.export_file("7/report.pdf")
    job_id = await harness.job(JobStatus.DONE, finished_with_file("7/report.pdf"))

    response = await harness.download(job_id)

    assert response.status_code == 200
    assert response.content == b"%PDF-1.7 report"
    assert response.headers["content-type"] == "application/pdf"
    assert response.headers["content-disposition"] == 'attachment; filename="tartarus-7.pdf"'


async def test_a_result_without_a_media_type_downloads_as_a_binary_stream(
    harness: Harness,
) -> None:
    harness.export_file("7/blob.bin")
    job_id = await harness.job(JobStatus.DONE, {"file": "7/blob.bin", "filename": "blob.bin"})

    response = await harness.download(job_id)

    assert response.headers["content-type"] == "application/octet-stream"


async def test_downloading_an_unknown_job_is_a_404(harness: Harness) -> None:
    assert (await harness.download(999)).status_code == 404


@pytest.mark.parametrize(
    "status", [JobStatus.PENDING, JobStatus.RUNNING, JobStatus.FAILED, JobStatus.INTERRUPTED]
)
async def test_a_job_that_is_not_done_has_nothing_to_download(
    harness: Harness, status: JobStatus
) -> None:
    harness.export_file("7/report.pdf")
    job_id = await harness.job(status, finished_with_file("7/report.pdf"))

    response = await harness.download(job_id)

    assert response.status_code == 409
    assert status.value in response.json()["error"]["message"]


async def test_a_file_that_has_been_removed_is_a_404(harness: Harness) -> None:
    job_id = await harness.job(JobStatus.DONE, finished_with_file("7/gone.pdf"))

    assert (await harness.download(job_id)).status_code == 404


@pytest.mark.parametrize("result", [None, {}, {"error": "x"}, {"file": 3, "filename": "x"}])
async def test_a_finished_job_that_names_no_file_has_nothing_to_download(
    harness: Harness, result: dict[str, Any] | None
) -> None:
    job_id = await harness.job(JobStatus.DONE, result)

    assert (await harness.download(job_id)).status_code == 404


@pytest.mark.parametrize("name", ["../secret.txt", "7/../../secret.txt"])
async def test_a_result_pointing_out_of_the_exports_directory_is_refused(
    harness: Harness, name: str
) -> None:
    (harness.exports.parent / "secret.txt").write_text("top secret")
    job_id = await harness.job(JobStatus.DONE, finished_with_file(name, "secret.txt"))

    response = await harness.download(job_id)

    assert response.status_code == 404
    assert b"top secret" not in response.content


async def test_an_absolute_path_in_the_result_is_refused(harness: Harness, tmp_path: Path) -> None:
    secret = tmp_path / "secret.txt"
    secret.write_text("top secret")
    job_id = await harness.job(JobStatus.DONE, finished_with_file(str(secret), "secret.txt"))

    response = await harness.download(job_id)

    assert response.status_code == 404
    assert b"top secret" not in response.content
