from collections.abc import Callable

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.analyses.ports import ReportOutcome
from app.analyses.runner import Runner
from app.db.models.analysis import AnalysisStatus, Severity
from tests.analyses.fakes import FakeCape, FakeReports
from tests.analyses.helpers import enqueue, load

type Factory = async_sessionmaker[AsyncSession]


async def test_a_new_runner_carries_on_tracking_what_a_dead_one_started(
    make_runner: Callable[[], Runner],
    session_factory: Factory,
    cape: FakeCape,
    reports: FakeReports,
) -> None:
    cape.script_for_new_tasks = ["running", "completed", "reported"]
    reports.outcome = ReportOutcome(2.0, Severity.LOW, [], {"signatures": []})
    analysis_id = await enqueue(session_factory)
    before_the_crash = make_runner()
    await before_the_crash.run_once()
    await before_the_crash.run_once()
    assert (await load(session_factory, analysis_id)).status is AnalysisStatus.RUNNING

    after_the_restart = make_runner()
    await after_the_restart.run_once()
    await after_the_restart.run_once()

    done = await load(session_factory, analysis_id)
    assert done.status is AnalysisStatus.DONE
    assert done.score == 2.0
    assert [call for call in cape.calls if call[0] == "create"] == [("create", "benign.exe")]


async def test_a_new_runner_does_not_resubmit_an_analysis_that_died_before_its_task_id_was_saved(
    make_runner: Callable[[], Runner], session_factory: Factory, cape: FakeCape
) -> None:
    analysis_id = await enqueue(session_factory)
    cape.create_errors = [SystemExit]
    with pytest.raises(SystemExit):  # the process dies between claiming and saving the task id
        await make_runner().run_once()
    cape.create_errors = []

    await make_runner().run_once()

    lost = await load(session_factory, analysis_id)
    assert lost.status is AnalysisStatus.FAILED
    assert cape.created == []
