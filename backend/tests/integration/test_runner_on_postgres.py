from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.analyses.ports import ReportOutcome
from app.analyses.runner import Runner, RunnerConfig
from app.db import analysis_repository as repository
from app.db.models.analysis import AnalysisPhase, AnalysisStatus, Severity
from tests.analyses.fakes import CAPE_STARTED_ON, FakeCape, FakeIngester, FakeReports, FakeSamples
from tests.test_analysis_repository import OPTIONS, SHA_A, make_sample

pytestmark = pytest.mark.integration

OUTCOME = ReportOutcome(
    score=7.5,
    max_severity=Severity.HIGH,
    detected_families=["emotet", "trickbot"],
    summary={"signatures": [{"name": "persistence", "severity": 3}], "process_count": 4},
)


async def test_an_analysis_goes_from_queued_to_done_on_postgres(
    session_factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    cape = FakeCape()
    cape.script_for_new_tasks = ["pending", "running", "completed", "reported"]
    reports = FakeReports()
    reports.outcome = OUTCOME
    plain = tmp_path / "plain"
    plain.mkdir()
    runner = Runner(
        session_factory,
        cape,
        FakeSamples(plain),
        reports,
        FakeIngester(),
        RunnerConfig(
            cape_storage_path=tmp_path,
            guest_label="win",
            poll_interval=3600.0,
            unreachable_grace=120.0,
        ),
    )
    async with session_factory() as session:
        await repository.add_sample_if_new(session, make_sample())
        created = await repository.create_analysis(
            session, sample_sha256=SHA_A, filename="benign.exe", options=OPTIONS
        )

    for _ in range(5):
        await runner.run_once()

    async with session_factory() as session:
        done = await repository.get_analysis(session, created.id)
    assert done is not None
    assert done.status is AnalysisStatus.DONE
    assert done.phase is AnalysisPhase.FINAL
    assert done.cape_task_id == 100
    assert (done.score, done.max_severity) == (7.5, Severity.HIGH)
    assert done.detected_families == ["emotet", "trickbot"]
    assert done.summary == {**OUTCOME.summary, "lane_counts": {}}
    assert done.started_at == CAPE_STARTED_ON
    assert done.finished_at is not None
    assert reports.paths == [tmp_path / "analyses" / "100" / "reports" / "report.json"]
