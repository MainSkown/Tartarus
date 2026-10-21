from dataclasses import replace
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.analyses.defender import DefenderStatus, DefenderVerdict
from app.analyses.ports import (
    IngestFailedError,
    IngestResult,
    ReportOutcome,
    ReportUnreadableError,
)
from app.analyses.runner import Runner
from app.annotations.validation import Target
from app.cape.errors import CapeTaskNotFound
from app.db import analysis_repository as repository
from app.db import annotation_repository
from app.db.base import utc_now
from app.db.models.analysis import AnalysisPhase, AnalysisStatus, Severity
from app.db.models.annotation import TargetType
from tests.analyses.fakes import FakeCape, FakeIngester, FakeReports
from tests.analyses.helpers import adopt_by_cape, load

type Factory = async_sessionmaker[AsyncSession]

REPORT_PATH = Path("/cape-storage/analyses/7/reports/report.json")
OUTCOME = ReportOutcome(
    score=7.5, max_severity=None, detected_families=[], summary={"process_count": 2}
)
REMOVED_SAMPLE = DefenderVerdict(
    status=DefenderStatus.REMOVED, sample_removed=True, blocked_before_run=True, threats=[]
)
INDEXED = IngestResult(
    event_count=1204,
    lane_counts={"api": 900, "process": 300, "network": 4},
    defender=REMOVED_SAMPLE,
    hidden_events={"windows-background": 3000, "cape-tooling": 12},
)


async def reported_analysis(session_factory: Factory, cape: FakeCape, reports: FakeReports) -> int:
    reports.outcome = OUTCOME
    cape.scripts[7] = ["reported"]
    return await adopt_by_cape(session_factory, 7)


async def test_a_finished_ingest_ends_done_with_the_event_count_and_lane_counts(
    runner: Runner,
    session_factory: Factory,
    cape: FakeCape,
    reports: FakeReports,
    ingester: FakeIngester,
) -> None:
    ingester.result = INDEXED
    analysis_id = await reported_analysis(session_factory, cape, reports)

    await runner.run_once()

    done = await load(session_factory, analysis_id)
    assert done.status is AnalysisStatus.DONE
    assert done.phase is AnalysisPhase.FINAL
    assert done.event_count == 1204
    assert done.summary == {
        "process_count": 2,
        "lane_counts": INDEXED.lane_counts,
        "defender": REMOVED_SAMPLE.model_dump(mode="json"),
        "hidden_events": {"windows-background": 3000, "cape-tooling": 12},
    }
    assert ingester.requests == [(analysis_id, REPORT_PATH)]


async def test_an_ingest_without_a_verdict_stores_none_and_nothing_hidden(
    runner: Runner,
    session_factory: Factory,
    cape: FakeCape,
    reports: FakeReports,
    ingester: FakeIngester,
) -> None:
    ingester.result = IngestResult(event_count=3, lane_counts={"api": 3})
    analysis_id = await reported_analysis(session_factory, cape, reports)

    await runner.run_once()

    done = await load(session_factory, analysis_id)
    assert done.summary is not None
    assert done.summary["defender"] is None
    assert done.summary["hidden_events"] == {}


async def test_a_failed_ingest_ends_report_failed_with_its_message_and_no_events(
    runner: Runner,
    session_factory: Factory,
    cape: FakeCape,
    reports: FakeReports,
    ingester: FakeIngester,
) -> None:
    ingester.result = IngestFailedError("Indexing the events failed: 3 events rejected")
    analysis_id = await reported_analysis(session_factory, cape, reports)

    await runner.run_once()

    failed = await load(session_factory, analysis_id)
    assert failed.status is AnalysisStatus.REPORT_FAILED
    assert failed.error == "Indexing the events failed: 3 events rejected"
    assert failed.event_count == 0
    assert failed.finished_at is not None
    assert failed.summary is None


async def test_an_unreadable_report_is_not_indexed(
    runner: Runner,
    session_factory: Factory,
    cape: FakeCape,
    reports: FakeReports,
    ingester: FakeIngester,
) -> None:
    analysis_id = await reported_analysis(session_factory, cape, reports)
    reports.outcome = ReportUnreadableError("report is missing: report.json")

    await runner.run_once()

    failed = await load(session_factory, analysis_id)
    assert failed.status is AnalysisStatus.REPORT_FAILED
    assert failed.error == "report is missing: report.json"
    assert ingester.requests == []


@pytest.mark.parametrize("earlier", [AnalysisStatus.DONE, AnalysisStatus.REPORT_FAILED])
async def test_an_analysis_put_back_to_ingesting_is_ingested_again_from_cape_s_reported_task(  # noqa: PLR0913, PLR0917
    runner: Runner,
    session_factory: Factory,
    cape: FakeCape,
    reports: FakeReports,
    ingester: FakeIngester,
    earlier: AnalysisStatus,
) -> None:
    ingester.result = INDEXED
    analysis_id = await reported_analysis(session_factory, cape, reports)
    async with session_factory() as session:
        await repository.update_analysis(
            session, analysis_id, status=earlier, error="earlier failure", finished_at=utc_now()
        )
        await repository.update_analysis(
            session, analysis_id, status=AnalysisStatus.INGESTING, error=None, finished_at=None
        )

    await runner.run_once()

    again = await load(session_factory, analysis_id)
    assert again.status is AnalysisStatus.DONE
    assert again.event_count == 1204
    assert ingester.requests == [(analysis_id, REPORT_PATH)]


async def test_a_reingest_keeps_the_tags_and_notes_of_the_analysis(
    runner: Runner,
    session_factory: Factory,
    cape: FakeCape,
    reports: FakeReports,
    ingester: FakeIngester,
) -> None:
    ingester.result = INDEXED
    analysis_id = await reported_analysis(session_factory, cape, reports)
    async with session_factory() as session:
        await annotation_repository.add_tag(
            session, analysis_id, Target(TargetType.EVENT, "evt-1"), "c2"
        )
        await annotation_repository.add_note(
            session, analysis_id, Target(TargetType.ANALYSIS), "kept"
        )
        await repository.update_analysis(session, analysis_id, status=AnalysisStatus.DONE)
        assert await repository.begin_reingest(session, analysis_id)

    await runner.run_once()

    async with session_factory() as session:
        kept = await annotation_repository.annotations_of_analysis(session, analysis_id)
    assert (await load(session_factory, analysis_id)).status is AnalysisStatus.DONE
    assert [(t.tag, t.target_ref) for t in kept.tags] == [("c2", "evt-1")]
    assert [note.body for note in kept.notes] == ["kept"]


async def test_a_reingest_of_a_task_cape_has_forgotten_ends_report_failed_instead_of_hanging(
    runner: Runner,
    session_factory: Factory,
    cape: FakeCape,
    ingester: FakeIngester,
) -> None:
    cape.scripts[7] = [CapeTaskNotFound("tasks/status", 7, "Task does not exist")]
    analysis_id = await adopt_by_cape(session_factory, 7, AnalysisStatus.INGESTING)

    await runner.run_once()

    failed = await load(session_factory, analysis_id)
    assert failed.status is AnalysisStatus.REPORT_FAILED
    assert failed.error is not None
    assert "task 7" in failed.error
    assert ingester.requests == []
    assert await _active_count(session_factory) == 0


async def _active_count(session_factory: Factory) -> int:
    async with session_factory() as session:
        return len(await repository.get_active_analyses(session))


@pytest.mark.parametrize(
    ("signatures", "detections", "expected"),
    [
        (Severity.MEDIUM, Severity.HIGH, Severity.HIGH),
        (Severity.CRITICAL, Severity.LOW, Severity.CRITICAL),
        (None, Severity.LOW, Severity.LOW),
        (Severity.LOW, None, Severity.LOW),
        (None, None, None),
    ],
)
async def test_max_severity_is_the_highest_of_the_signatures_and_the_indexed_detections(  # noqa: PLR0913, PLR0917 - fixtures and parameters
    runner: Runner,
    session_factory: Factory,
    cape: FakeCape,
    reports: FakeReports,
    ingester: FakeIngester,
    signatures: Severity | None,
    detections: Severity | None,
    expected: Severity | None,
) -> None:
    ingester.result = IngestResult(
        event_count=3, lane_counts={"api": 3}, max_alert_severity=detections
    )
    reports.outcome = replace(OUTCOME, max_severity=signatures)
    cape.scripts[7] = ["reported"]
    analysis_id = await adopt_by_cape(session_factory, 7)

    await runner.run_once()

    assert (await load(session_factory, analysis_id)).max_severity is expected
