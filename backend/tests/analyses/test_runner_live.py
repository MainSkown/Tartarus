import dataclasses
import logging
from collections.abc import Callable

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.analyses.ports import IngestResult, ReportOutcome
from app.analyses.runner import Runner, RunnerConfig
from app.cape.errors import CapeTaskNotFound, CapeUnreachable
from app.db.models.analysis import AnalysisStatus
from tests.analyses.fakes import (
    CAPE_STARTED_ON,
    FakeCape,
    FakeClock,
    FakeIngester,
    FakeLive,
    FakeReports,
    FakeSamples,
)
from tests.analyses.guest_fakes import ScriptedGuestControl
from tests.analyses.helpers import adopt_by_cape, as_utc, load

type Factory = async_sessionmaker[AsyncSession]

TASK_ID = 7
OUTCOME = ReportOutcome(score=1.0, max_severity=None, detected_families=[], summary={})
STOP_PATIENCE_S = 0.05
FORGOTTEN = CapeTaskNotFound("tasks/status", TASK_ID, "Task does not exist")


@pytest.fixture
def live() -> FakeLive:
    return FakeLive()


@pytest.fixture
def make_live_runner(  # noqa: PLR0913, PLR0917 - a fixture assembling every fake
    session_factory: Factory,
    cape: FakeCape,
    samples: FakeSamples,
    reports: FakeReports,
    ingester: FakeIngester,
    guests: ScriptedGuestControl,
    clock: FakeClock,
    config: RunnerConfig,
    live: FakeLive,
) -> Callable[[], Runner]:
    patient = dataclasses.replace(config, live_stop_timeout=STOP_PATIENCE_S)

    def build() -> Runner:
        return Runner(
            session_factory,
            cape,
            samples,
            reports,
            ingester,
            guests,
            patient,
            clock=clock,
            live=live,
        )

    return build


@pytest.fixture
def live_runner(make_live_runner: Callable[[], Runner]) -> Runner:
    return make_live_runner()


async def run_ticks(runner: Runner, count: int) -> None:
    for _ in range(count):
        await runner.run_once()


async def test_collection_starts_once_when_the_analysis_becomes_running(
    live_runner: Runner, session_factory: Factory, cape: FakeCape, live: FakeLive
) -> None:
    cape.scripts[TASK_ID] = ["pending", "running", "running", "running"]
    analysis_id = await adopt_by_cape(session_factory, TASK_ID)

    await run_ticks(live_runner, 4)

    assert live.started == [(analysis_id, TASK_ID, CAPE_STARTED_ON)]
    assert live.stopped == []


async def test_collection_does_not_start_while_the_analysis_is_only_starting(
    live_runner: Runner, session_factory: Factory, cape: FakeCape, live: FakeLive
) -> None:
    cape.scripts[TASK_ID] = ["pending"]
    await adopt_by_cape(session_factory, TASK_ID)

    await run_ticks(live_runner, 3)

    assert live.journal == []


async def test_a_runner_that_finds_the_analysis_already_running_starts_collecting_it(
    make_live_runner: Callable[[], Runner],
    session_factory: Factory,
    cape: FakeCape,
    live: FakeLive,
) -> None:
    cape.scripts[TASK_ID] = ["running"]
    started_on = as_utc(CAPE_STARTED_ON)
    analysis_id = await adopt_by_cape(
        session_factory, TASK_ID, AnalysisStatus.RUNNING, started_at=started_on
    )

    await make_live_runner().run_once()

    assert [(a, t, as_utc(s)) for a, t, s in live.started] == [(analysis_id, TASK_ID, started_on)]


async def test_a_second_runner_on_the_same_run_starts_collecting_again(
    make_live_runner: Callable[[], Runner], session_factory: Factory, cape: FakeCape, live: FakeLive
) -> None:
    cape.scripts[TASK_ID] = ["pending", "running", "running"]
    await adopt_by_cape(session_factory, TASK_ID)
    first = make_live_runner()
    await run_ticks(first, 2)

    await make_live_runner().run_once()

    assert len(live.started) == 2


async def test_leaving_running_stops_the_collection_before_the_status_changes(
    live_runner: Runner, session_factory: Factory, cape: FakeCape, live: FakeLive
) -> None:
    cape.scripts[TASK_ID] = ["running", "completed"]
    analysis_id = await adopt_by_cape(session_factory, TASK_ID)
    seen: list[AnalysisStatus] = []

    async def note_status(_: int) -> None:
        seen.append((await load(session_factory, analysis_id)).status)

    live.on_stop = note_status

    await run_ticks(live_runner, 2)

    assert live.stopped == [analysis_id]
    assert seen == [AnalysisStatus.RUNNING]
    assert (await load(session_factory, analysis_id)).status is AnalysisStatus.PROCESSING


async def test_the_collection_is_drained_before_the_events_are_ingested(  # noqa: PLR0913, PLR0917 - pytest fixtures
    live_runner: Runner,
    session_factory: Factory,
    cape: FakeCape,
    reports: FakeReports,
    ingester: FakeIngester,
    live: FakeLive,
) -> None:
    cape.scripts[TASK_ID] = ["running", "reported"]
    reports.outcome = OUTCOME
    ingester.result = IngestResult(3, {})
    analysis_id = await adopt_by_cape(session_factory, TASK_ID)
    real_ingest = ingester.ingest

    async def ingest_and_note(analysis: int, report_path, **kwargs):  # type: ignore[no-untyped-def]
        live.journal.append(("ingest", analysis))
        return await real_ingest(analysis, report_path, **kwargs)

    ingester.ingest = ingest_and_note  # type: ignore[method-assign]

    await run_ticks(live_runner, 2)

    assert live.journal == [("start", analysis_id), ("stop", analysis_id), ("ingest", analysis_id)]


@pytest.mark.parametrize(
    ("script", "ending"),
    [
        (["running", "failed_analysis"], AnalysisStatus.FAILED),
        (["running", "failed_reporting"], AnalysisStatus.REPORT_FAILED),
        (
            ["running", CapeTaskNotFound("tasks/status", TASK_ID, "Task does not exist")],
            AnalysisStatus.FAILED,
        ),
    ],
    ids=["cape failed it", "cape failed reporting", "cape forgot the task"],
)
async def test_every_way_out_of_running_stops_the_collection(  # noqa: PLR0913, PLR0917 - pytest fixtures
    live_runner: Runner,
    session_factory: Factory,
    cape: FakeCape,
    live: FakeLive,
    script: list[str | Exception],
    ending: AnalysisStatus,
) -> None:
    cape.scripts[TASK_ID] = script
    analysis_id = await adopt_by_cape(session_factory, TASK_ID)

    await run_ticks(live_runner, 2)

    assert (await load(session_factory, analysis_id)).status is ending
    assert live.stopped == [analysis_id]


async def test_an_outage_longer_than_the_grace_period_stops_the_collection_too(  # noqa: PLR0913, PLR0917 - pytest fixtures
    live_runner: Runner,
    session_factory: Factory,
    cape: FakeCape,
    clock: FakeClock,
    live: FakeLive,
    config: RunnerConfig,
) -> None:
    cape.scripts[TASK_ID] = ["running", CapeUnreachable("tasks/status", "ConnectError")]
    analysis_id = await adopt_by_cape(session_factory, TASK_ID)
    await run_ticks(live_runner, 2)
    assert live.stopped == []

    clock.advance(config.unreachable_grace + 1)
    await live_runner.run_once()

    assert (await load(session_factory, analysis_id)).status is AnalysisStatus.FAILED
    assert live.stopped == [analysis_id]


async def test_an_analysis_that_never_ran_has_nothing_to_stop(
    live_runner: Runner, session_factory: Factory, cape: FakeCape, live: FakeLive
) -> None:
    cape.scripts[TASK_ID] = ["pending", "completed"]
    analysis_id = await adopt_by_cape(session_factory, TASK_ID)

    await run_ticks(live_runner, 2)

    assert (await load(session_factory, analysis_id)).status is AnalysisStatus.PROCESSING
    assert live.journal == []


async def test_the_collection_is_stopped_only_once(
    live_runner: Runner, session_factory: Factory, cape: FakeCape, live: FakeLive
) -> None:
    cape.scripts[TASK_ID] = ["running", "completed", "completed", "completed"]
    await adopt_by_cape(session_factory, TASK_ID)

    await run_ticks(live_runner, 4)

    assert len(live.stopped) == 1


async def test_a_failing_stop_does_not_stop_the_runner(
    live_runner: Runner,
    session_factory: Factory,
    cape: FakeCape,
    live: FakeLive,
    caplog: pytest.LogCaptureFixture,
) -> None:
    cape.scripts[TASK_ID] = ["running", "completed"]
    live.stop_error = RuntimeError("collector exploded")
    analysis_id = await adopt_by_cape(session_factory, TASK_ID)

    with caplog.at_level(logging.ERROR):
        await run_ticks(live_runner, 2)

    assert (await load(session_factory, analysis_id)).status is AnalysisStatus.PROCESSING
    assert "collector exploded" in caplog.text


async def test_a_stop_that_hangs_is_given_up_on(
    live_runner: Runner, session_factory: Factory, cape: FakeCape, live: FakeLive
) -> None:
    cape.scripts[TASK_ID] = ["running", "completed"]
    live.hang_on_stop = True
    analysis_id = await adopt_by_cape(session_factory, TASK_ID)

    await run_ticks(live_runner, 2)

    assert (await load(session_factory, analysis_id)).status is AnalysisStatus.PROCESSING


async def test_a_failing_start_does_not_stop_the_runner_and_is_tried_again_next_tick(
    live_runner: Runner, session_factory: Factory, cape: FakeCape, live: FakeLive
) -> None:
    cape.scripts[TASK_ID] = ["running"]
    live.start_errors = [RuntimeError("no logs yet")]
    analysis_id = await adopt_by_cape(session_factory, TASK_ID)

    await live_runner.run_once()
    assert (await load(session_factory, analysis_id)).status is AnalysisStatus.RUNNING
    assert live.started == []

    await live_runner.run_once()

    assert [started[0] for started in live.started] == [analysis_id]


async def test_a_runner_without_a_live_port_works_as_before(
    runner: Runner, session_factory: Factory, cape: FakeCape
) -> None:
    cape.scripts[TASK_ID] = ["running", "completed"]
    analysis_id = await adopt_by_cape(session_factory, TASK_ID)

    await run_ticks(runner, 2)

    assert (await load(session_factory, analysis_id)).status is AnalysisStatus.PROCESSING


async def test_re_ingesting_a_finished_analysis_touches_no_collection(
    live_runner: Runner,
    session_factory: Factory,
    cape: FakeCape,
    reports: FakeReports,
    live: FakeLive,
) -> None:
    cape.scripts[TASK_ID] = ["reported"]
    reports.outcome = OUTCOME
    analysis_id = await adopt_by_cape(session_factory, TASK_ID, AnalysisStatus.INGESTING)

    await live_runner.run_once()

    assert (await load(session_factory, analysis_id)).status is AnalysisStatus.DONE
    assert live.journal == []
