import logging

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.analyses.ports import IngestResult, ReportOutcome
from app.analyses.runner import Runner
from app.db import analysis_repository as repository
from tests.analyses.fakes import FakeCape, FakeIngester, FakeReports
from tests.analyses.helpers import adopt_by_cape, app_log_text, enqueue, load
from tests.test_analysis_repository import OPTIONS

type Factory = async_sessionmaker[AsyncSession]

PASSWORD = "s3cret-Pass"  # noqa: S105
ARCHIVE = {"package": "zip", "archive_password": "infected", "archive_entry": "payload.exe"}
WINDOWS_INTERACTIVE = "interactive=1,nohuman=yes"


async def queue_archive(session_factory: Factory, **options: object) -> None:
    await enqueue(session_factory, "samples.zip", options={**OPTIONS, **ARCHIVE, **options})


async def test_an_archive_analysis_sends_the_zip_package_with_password_and_entry(
    runner: Runner, session_factory: Factory, cape: FakeCape
) -> None:
    await queue_archive(session_factory)

    await runner.run_once()

    task = cape.created[0]
    assert task["package"] == "zip"
    assert task["options"] == "password=infected,file=payload.exe"
    assert task["filename"] == "samples.zip"


async def test_the_archive_options_come_before_the_interactive_options(
    runner: Runner, session_factory: Factory, cape: FakeCape
) -> None:
    await queue_archive(session_factory, interactive=True)

    await runner.run_once()

    assert cape.created[0]["options"] == f"password=infected,file=payload.exe,{WINDOWS_INTERACTIVE}"


async def test_an_analysis_without_archive_fields_sends_no_archive_options(
    runner: Runner, session_factory: Factory, cape: FakeCape
) -> None:
    await enqueue(session_factory, options={**OPTIONS, "interactive": True})

    await runner.run_once()

    assert cape.created[0]["options"] == WINDOWS_INTERACTIVE


async def test_the_password_reaches_cape_and_no_log_line(
    runner: Runner,
    session_factory: Factory,
    cape: FakeCape,
    caplog: pytest.LogCaptureFixture,
) -> None:
    await queue_archive(session_factory, archive_password=PASSWORD)

    with caplog.at_level(logging.DEBUG):
        await runner.run_once()

    assert cape.created[0]["options"] == f"password={PASSWORD},file=payload.exe"
    assert PASSWORD not in app_log_text(caplog)


ENTRY_SHA256 = "4b322b00" * 8
ARCHIVE_SUMMARY = {"process_count": 2, "sample": {"name": "samples.zip", "type": "Zip archive"}}


@pytest.fixture(autouse=True)
def reported_task_7(cape: FakeCape, reports: FakeReports) -> None:
    reports.outcome = ReportOutcome(
        score=1.0, max_severity=None, detected_families=[], summary=ARCHIVE_SUMMARY
    )
    cape.scripts[7] = ["reported"]


def ingest_result(entry_sha256: str | None) -> IngestResult:
    return IngestResult(event_count=3, lane_counts={}, entry_sha256=entry_sha256)


async def adopt_task_7(session_factory: Factory, options: dict[str, object]) -> int:
    return await adopt_by_cape(session_factory, 7, options={**OPTIONS, **options})


async def test_the_ingest_of_an_archive_analysis_is_told_the_entry(
    runner: Runner, session_factory: Factory, ingester: FakeIngester
) -> None:
    analysis_id = await adopt_task_7(session_factory, ARCHIVE)

    await runner.run_once()

    assert ingester.archive_entries == {analysis_id: "payload.exe"}


async def test_the_entry_hash_is_stored_in_the_summary_beside_the_sample_info(
    runner: Runner, session_factory: Factory, ingester: FakeIngester
) -> None:
    ingester.result = ingest_result(ENTRY_SHA256)
    analysis_id = await adopt_task_7(session_factory, ARCHIVE)

    await runner.run_once()

    assert (await load(session_factory, analysis_id)).summary["sample"] == {
        "name": "samples.zip",
        "type": "Zip archive",
        "entry_sha256": ENTRY_SHA256,
    }


async def test_an_entry_nothing_ran_from_leaves_the_summary_as_the_report_gave_it(
    runner: Runner, session_factory: Factory, ingester: FakeIngester
) -> None:
    ingester.result = ingest_result(None)
    analysis_id = await adopt_task_7(session_factory, ARCHIVE)

    await runner.run_once()

    assert (await load(session_factory, analysis_id)).summary["sample"] == (
        ARCHIVE_SUMMARY["sample"]
    )


async def test_an_analysis_without_an_archive_entry_is_ingested_without_one(
    runner: Runner, session_factory: Factory, ingester: FakeIngester
) -> None:
    analysis_id = await adopt_task_7(session_factory, {})

    await runner.run_once()

    assert ingester.archive_entries == {analysis_id: None}
    assert "entry_sha256" not in (await load(session_factory, analysis_id)).summary["sample"]


async def test_a_reingest_computes_the_entry_hash_again(
    runner: Runner, session_factory: Factory, cape: FakeCape, ingester: FakeIngester
) -> None:
    ingester.result = ingest_result(None)
    analysis_id = await adopt_task_7(session_factory, ARCHIVE)
    await runner.run_once()
    ingester.result = ingest_result(ENTRY_SHA256)
    cape.scripts[7] = ["reported"]
    async with session_factory() as session:
        assert await repository.begin_reingest(session, analysis_id)

    await runner.run_once()

    again = await load(session_factory, analysis_id)
    assert again.summary["sample"]["entry_sha256"] == ENTRY_SHA256
