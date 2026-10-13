import threading
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.analyses.ports import ReportOutcome, ReportUnreadableError
from app.analyses.runner import Runner
from app.cape.status import CapeProgress
from app.db import analysis_repository as repository
from app.db.models.analysis import ACTIVE_STATUSES, AnalysisPhase, AnalysisStatus, Severity
from tests.analyses.fakes import CAPE_STARTED_ON, FakeCape, FakeReports
from tests.analyses.helpers import adopt_by_cape, as_utc, enqueue, load

type Factory = async_sessionmaker[AsyncSession]

OUTCOME = ReportOutcome(
    score=7.5,
    max_severity=Severity.HIGH,
    detected_families=["emotet"],
    summary={"signatures": [{"name": "persistence", "severity": 3}]},
)


def test_every_cape_progress_but_unknown_is_an_analysis_status() -> None:
    statuses = {status.value for status in AnalysisStatus}

    assert {p.value for p in CapeProgress if p is not CapeProgress.UNKNOWN} <= statuses


def test_cape_progress_that_keeps_the_analysis_going_is_an_active_status() -> None:
    going_on = {CapeProgress.FAILED, CapeProgress.REPORT_FAILED, CapeProgress.UNKNOWN}
    active = {status.value for status in ACTIVE_STATUSES}

    assert {p.value for p in CapeProgress if p not in going_on} == active


async def test_an_analysis_goes_from_queued_to_done_through_every_state(
    runner: Runner,
    session_factory: Factory,
    cape: FakeCape,
    reports: FakeReports,
) -> None:
    cape.script_for_new_tasks = ["pending", "running", "completed", "reported"]
    reports.outcome = OUTCOME
    analysis_id = await enqueue(session_factory)
    seen: list[AnalysisStatus] = []

    for _ in range(5):
        await runner.run_once()
        seen.append((await load(session_factory, analysis_id)).status)

    assert seen == [
        AnalysisStatus.STARTING,  # submitted to CAPE
        AnalysisStatus.STARTING,  # CAPE: pending
        AnalysisStatus.RUNNING,
        AnalysisStatus.PROCESSING,
        AnalysisStatus.DONE,
    ]
    done = await load(session_factory, analysis_id)
    assert done.cape_task_id == 100
    assert (done.score, done.max_severity) == (7.5, Severity.HIGH)
    assert done.detected_families == ["emotet"]
    assert done.summary == OUTCOME.summary
    assert done.phase is AnalysisPhase.FINAL
    assert as_utc(done.started_at) == CAPE_STARTED_ON
    assert done.finished_at is not None
    assert done.error is None


async def test_the_report_is_read_only_after_cape_says_reported_and_off_the_event_loop(
    runner: Runner, session_factory: Factory, cape: FakeCape, reports: FakeReports
) -> None:
    reports.outcome = OUTCOME
    cape.scripts[7] = ["running", "completed", "reported"]
    analysis_id = await adopt_by_cape(session_factory, 7)

    await runner.run_once()
    await runner.run_once()
    assert reports.paths == []

    await runner.run_once()

    assert reports.paths == [Path("/cape-storage/analyses/7/reports/report.json")]
    assert reports.thread_ids != [threading.get_ident()]
    assert (await load(session_factory, analysis_id)).status is AnalysisStatus.DONE


async def test_the_analysis_is_ingesting_before_the_report_is_read(
    runner: Runner, session_factory: Factory, cape: FakeCape, reports: FakeReports
) -> None:
    reports.outcome = RuntimeError("disk hiccup")
    cape.scripts[7] = ["reported"]
    analysis_id = await adopt_by_cape(session_factory, 7)

    await runner.run_once()

    assert (await load(session_factory, analysis_id)).status is AnalysisStatus.INGESTING


async def test_an_unreadable_report_ends_the_analysis_as_report_failed(
    runner: Runner, session_factory: Factory, cape: FakeCape, reports: FakeReports
) -> None:
    reports.outcome = ReportUnreadableError("report.json is not a CAPE report")
    cape.scripts[7] = ["reported"]
    analysis_id = await adopt_by_cape(session_factory, 7)

    await runner.run_once()

    failed = await load(session_factory, analysis_id)
    assert failed.status is AnalysisStatus.REPORT_FAILED
    assert failed.error == "report.json is not a CAPE report"
    assert failed.finished_at is not None


@pytest.mark.parametrize(
    ("cape_status", "ended_as"),
    [
        ("failed_analysis", AnalysisStatus.FAILED),
        ("failed_processing", AnalysisStatus.FAILED),
        ("failed_reporting", AnalysisStatus.REPORT_FAILED),
    ],
)
async def test_a_task_that_cape_ends_badly_ends_the_analysis_with_cape_s_status(  # noqa: PLR0913, PLR0917
    runner: Runner,
    session_factory: Factory,
    cape: FakeCape,
    reports: FakeReports,
    cape_status: str,
    ended_as: AnalysisStatus,
) -> None:
    cape.scripts[7] = [cape_status]
    analysis_id = await adopt_by_cape(session_factory, 7, AnalysisStatus.RUNNING)

    await runner.run_once()

    ended = await load(session_factory, analysis_id)
    assert ended.status is ended_as
    assert ended.error == f"CAPE ended the task as {cape_status}"
    assert ended.finished_at is not None
    assert reports.paths == []


async def test_an_analysis_never_moves_back_to_an_earlier_state(
    runner: Runner, session_factory: Factory, cape: FakeCape
) -> None:
    cape.scripts[7] = ["running", "pending"]
    analysis_id = await adopt_by_cape(session_factory, 7)

    await runner.run_once()
    await runner.run_once()

    assert (await load(session_factory, analysis_id)).status is AnalysisStatus.RUNNING


async def test_started_at_is_taken_from_cape_once_and_kept(
    runner: Runner, session_factory: Factory, cape: FakeCape
) -> None:
    cape.scripts[7] = ["running", "completed"]
    analysis_id = await adopt_by_cape(session_factory, 7)

    await runner.run_once()
    await runner.run_once()

    assert as_utc((await load(session_factory, analysis_id)).started_at) == CAPE_STARTED_ON
    assert cape.calls.count(("view", 7)) == 1


async def test_a_task_that_skips_running_still_gets_a_start_time(
    runner: Runner, session_factory: Factory, cape: FakeCape
) -> None:
    cape.scripts[7] = ["completed"]
    analysis_id = await adopt_by_cape(session_factory, 7)

    await runner.run_once()

    quick = await load(session_factory, analysis_id)
    assert quick.status is AnalysisStatus.PROCESSING
    assert as_utc(quick.started_at) == CAPE_STARTED_ON


async def test_an_analysis_that_has_no_cape_task_cannot_be_tracked_and_is_not_resubmitted(
    runner: Runner, session_factory: Factory, cape: FakeCape
) -> None:
    analysis_id = await enqueue(session_factory)
    async with session_factory() as session:
        await repository.update_analysis(session, analysis_id, status=AnalysisStatus.STARTING)

    await runner.run_once()

    lost = await load(session_factory, analysis_id)
    assert lost.status is AnalysisStatus.FAILED
    assert lost.error is not None
    assert "CAPE task" in lost.error
    assert cape.calls == []
