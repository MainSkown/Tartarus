"""The report job on a real index: the handler gathers from the real views and renders for real."""

import asyncio
import io
from collections.abc import AsyncIterator
from typing import Any

import pypdf
import pytest

from app.api.dependencies import get_exports_path, get_job_runner
from app.api.export import router as export_router
from app.api.jobs import router as jobs_router
from app.db.models.job import JobType
from app.export.report.job import export_report_handler
from app.jobs.runner import JobRunner
from app.views.attack_table import load_attack_table
from tests.integration.views.conftest import ViewStack

pytestmark = pytest.mark.integration

POLL_LIMIT_S = 60


@pytest.fixture
async def reporting(view_stack: ViewStack) -> AsyncIterator[ViewStack]:
    exports = view_stack.storage_root.parent / "exports"
    runner = JobRunner(view_stack.factory, exports)
    runner.register(
        JobType.EXPORT_REPORT,
        export_report_handler(
            view_stack.factory, view_stack.index, view_stack.storage_root, load_attack_table()
        ),
    )
    await runner.start()
    for router in (export_router, jobs_router):
        view_stack.app.include_router(router, prefix="/api")
    view_stack.app.dependency_overrides[get_job_runner] = lambda: runner
    view_stack.app.dependency_overrides[get_exports_path] = lambda: exports
    yield view_stack
    await runner.stop()


async def finished(stack: ViewStack, job_id: int) -> dict[str, Any]:
    async with asyncio.timeout(POLL_LIMIT_S):
        while True:
            job = (await stack.client.get(f"/api/jobs/{job_id}")).json()
            if job["status"] not in ("pending", "running"):
                return job  # type: ignore[no-any-return]
            await asyncio.sleep(0.1)


async def export_report(stack: ViewStack, format_: str) -> tuple[dict[str, Any], bytes]:
    response = await stack.client.post(
        f"/api/analyses/{stack.analysis_id}/export/report", json={"format": format_}
    )
    assert response.status_code == 202, response.text
    job_id = response.json()["id"]
    job = await finished(stack, job_id)
    assert job["status"] == "done", job
    download = await stack.client.get(f"/api/jobs/{job_id}/download")
    assert download.status_code == 200
    return job, download.content


async def test_report_job_html_has_the_sample_and_its_findings(reporting: ViewStack) -> None:
    job, content = await export_report(reporting, "html")

    page = content.decode("utf-8")
    assert job["progress"] == 100
    assert "benign.exe" in page
    assert f"#{reporting.analysis_id}" in page


async def test_report_job_pdf_opens_and_has_the_sample_name(reporting: ViewStack) -> None:
    job, content = await export_report(reporting, "pdf")

    reader = pypdf.PdfReader(io.BytesIO(content))
    text = " ".join(page.extract_text() for page in reader.pages)
    assert job["result"]["filename"] == f"tartarus-report-{reporting.analysis_id}.pdf"
    assert "benign.exe" in text
