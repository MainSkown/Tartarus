import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import replace

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.analyses import runner as runner_module
from app.analyses.runner import Runner, RunnerConfig, build_runner
from app.config import Settings
from app.db.models.analysis import AnalysisStatus
from tests.analyses.fakes import FakeCape, FakeIngester, FakeReports, FakeSamples
from tests.analyses.helpers import adopt_by_cape, enqueue, load

type Factory = async_sessionmaker[AsyncSession]

PATIENCE_SECONDS = 2.0


async def eventually(condition: Callable[[], bool | Awaitable[bool]]) -> None:
    async def holds() -> bool:
        outcome = condition()
        return outcome if isinstance(outcome, bool) else await outcome

    async def wait() -> None:
        while not await holds():  # noqa: ASYNC110 - the condition is not an event
            await asyncio.sleep(0.001)

    await asyncio.wait_for(wait(), PATIENCE_SECONDS)


async def test_the_loop_checks_for_work_as_soon_as_it_starts(
    runner: Runner, session_factory: Factory, cape: FakeCape
) -> None:
    analysis_id = await enqueue(session_factory)
    runner.start()
    try:
        await eventually(lambda: ("create", "benign.exe") in cape.calls)
    finally:
        await runner.stop()

    assert (await load(session_factory, analysis_id)).status is AnalysisStatus.STARTING


async def test_a_nudge_triggers_a_tick_without_waiting_for_the_poll_interval(
    runner: Runner, session_factory: Factory, cape: FakeCape
) -> None:
    cape.scripts[7] = ["pending"]
    await adopt_by_cape(session_factory, 7)
    runner.start()
    try:
        await eventually(lambda: cape.status_calls() == 1)

        runner.nudge()
        await eventually(lambda: cape.status_calls() == 2)
        runner.nudge()
        await eventually(lambda: cape.status_calls() == 3)
    finally:
        await runner.stop()


async def test_a_nudge_given_while_a_tick_runs_is_not_lost(
    runner: Runner, session_factory: Factory, cape: FakeCape
) -> None:
    cape.scripts[7] = ["pending"]
    await adopt_by_cape(session_factory, 7)
    first_status_call = asyncio.Event()
    release = asyncio.Event()
    real_status = cape.task_status

    async def slow_status(task_id: int) -> str:
        first_status_call.set()
        await release.wait()
        return await real_status(task_id)

    cape.task_status = slow_status  # type: ignore[method-assign]
    runner.start()
    try:
        await asyncio.wait_for(first_status_call.wait(), PATIENCE_SECONDS)
        runner.nudge()
        cape.task_status = real_status  # type: ignore[method-assign]
        release.set()

        await eventually(lambda: cape.status_calls() >= 2)
    finally:
        await runner.stop()


def test_nudging_a_runner_that_never_started_is_harmless(runner: Runner) -> None:
    runner.nudge()
    runner.nudge()


async def test_a_failing_tick_does_not_stop_the_loop(
    runner: Runner,
    session_factory: Factory,
    cape: FakeCape,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_get_active = runner_module.get_active_analysis
    outage = [True]

    async def flaky_database(session: AsyncSession):
        if outage:
            outage.clear()
            raise ConnectionError("database restarting")
        return await real_get_active(session)

    monkeypatch.setattr(runner_module, "get_active_analysis", flaky_database)
    analysis_id = await enqueue(session_factory)
    runner.start()
    try:
        await eventually(lambda: not outage)
        runner.nudge()

        await eventually(lambda: ("create", "benign.exe") in cape.calls)
    finally:
        await runner.stop()
    assert (await load(session_factory, analysis_id)).cape_task_id == 100


async def test_stop_ends_the_loop_and_can_be_repeated(runner: Runner, cape: FakeCape) -> None:
    runner.start()
    await runner.stop()
    await runner.stop()

    runner.nudge()
    await asyncio.sleep(0.01)

    assert cape.calls == []


async def test_stop_lets_a_submission_in_flight_save_its_task_id(
    runner: Runner, session_factory: Factory, cape: FakeCape
) -> None:
    cape.create_gate = asyncio.Event()
    analysis_id = await enqueue(session_factory)
    runner.start()
    await eventually(lambda: ("create", "benign.exe") in cape.calls)

    stopping = asyncio.create_task(runner.stop())
    await asyncio.sleep(0.01)
    assert not stopping.done()
    cape.create_gate.set()
    await asyncio.wait_for(stopping, PATIENCE_SECONDS)

    assert (await load(session_factory, analysis_id)).cape_task_id == 100


async def test_stop_gives_up_on_a_tick_that_does_not_finish(  # noqa: PLR0913, PLR0917
    session_factory: Factory,
    cape: FakeCape,
    samples: FakeSamples,
    reports: FakeReports,
    ingester: FakeIngester,
    config: RunnerConfig,
) -> None:
    impatient = Runner(
        session_factory,
        cape,
        samples,
        reports,
        ingester,
        replace(config, shutdown_patience=0.01),
    )
    cape.create_gate = asyncio.Event()
    await enqueue(session_factory)
    impatient.start()
    await eventually(lambda: ("create", "benign.exe") in cape.calls)

    await asyncio.wait_for(impatient.stop(), PATIENCE_SECONDS)


async def test_starting_a_running_runner_again_is_an_error(runner: Runner) -> None:
    runner.start()
    try:
        with pytest.raises(RuntimeError, match="already started"):
            runner.start()
    finally:
        await runner.stop()


async def test_the_builder_wires_the_settings_into_a_runner(  # noqa: PLR0913, PLR0917
    settings: Settings,
    session_factory: Factory,
    cape: FakeCape,
    samples: FakeSamples,
    reports: FakeReports,
    ingester: FakeIngester,
) -> None:
    built = build_runner(
        session_factory,
        cape,
        samples,
        reports,
        ingester,
        settings.model_copy(update={"guest_label": "lab-win"}),
    )
    await enqueue(session_factory)

    await built.run_once()

    assert cape.created[0]["machine"] == "lab-win"
