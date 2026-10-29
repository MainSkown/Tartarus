import asyncio
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.analyses.ports import IngestResult, ReportOutcome
from app.analyses.runner import Runner, RunnerConfig
from app.db import analysis_repository as repository
from app.db.models.analysis import AnalysisStatus
from tests.analyses.fakes import (
    FakeCape,
    FakeClock,
    FakeIngester,
    FakeLive,
    FakeReports,
    FakeSamples,
)
from tests.analyses.guest_fakes import ScriptedGuestControl, guest_named
from tests.analyses.helpers import adopt_by_cape, enqueue, load
from tests.test_analysis_repository import OPTIONS

type Factory = async_sessionmaker[AsyncSession]

PATIENCE_SECONDS = 2.0
STARTED = datetime(2026, 10, 21, 9, 0, 0, tzinfo=UTC)
INTERACTIVE = {**OPTIONS, "interactive": True}
OUTCOME = ReportOutcome(score=1.0, max_severity=None, detected_families=[], summary={})


def on(guest: str, **extra: object) -> dict[str, object]:
    return {**OPTIONS, "guest": guest, **extra}


def at(seconds: float) -> datetime:
    return STARTED + timedelta(seconds=seconds)


class WallClock:
    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


class GatedIngester(FakeIngester):
    """Indexes only once the test lets it, and says when an ingest has begun."""

    def __init__(self) -> None:
        super().__init__()
        self.began = asyncio.Event()
        self.release = asyncio.Event()

    async def ingest(
        self,
        analysis_id: int,
        report_path: object,
        *,
        started_at: datetime | None = None,
        archive_entry: str | None = None,
    ) -> IngestResult:
        self.began.set()
        await self.release.wait()
        return await super().ingest(  # type: ignore[arg-type]
            analysis_id, report_path, started_at=started_at, archive_entry=archive_entry
        )


class AnnouncingGuestControl(ScriptedGuestControl):
    def __init__(self) -> None:
        super().__init__([guest_named("lab3"), guest_named("lab5")])
        self.finish_asked = asyncio.Event()

    async def finish_task(self, task_id: int, guest: str) -> None:
        await super().finish_task(task_id, guest)
        self.finish_asked.set()


@pytest.fixture
def guests() -> AnnouncingGuestControl:
    return AnnouncingGuestControl()


@pytest.fixture
def live() -> FakeLive:
    return FakeLive()


@pytest.fixture
def wall_clock() -> WallClock:
    return WallClock(at(50))


@pytest.fixture
def gated_ingester() -> GatedIngester:
    return GatedIngester()


@pytest.fixture
def make_parallel_runner(  # noqa: PLR0913, PLR0917 - a fixture assembling every fake
    session_factory: Factory,
    cape: FakeCape,
    samples: FakeSamples,
    reports: FakeReports,
    gated_ingester: GatedIngester,
    guests: AnnouncingGuestControl,
    clock: FakeClock,
    config: RunnerConfig,
    live: FakeLive,
    wall_clock: WallClock,
) -> Callable[[], Runner]:
    def build() -> Runner:
        return Runner(
            session_factory,
            cape,
            samples,
            reports,
            gated_ingester,
            guests,
            config,
            clock=clock,
            now=wall_clock,
            live=live,
        )

    return build


@pytest.fixture
def parallel_runner(make_parallel_runner: Callable[[], Runner]) -> Runner:
    return make_parallel_runner()


async def end(session_factory: Factory, analysis_id: int) -> None:
    async with session_factory() as session:
        await repository.update_analysis(session, analysis_id, status=AnalysisStatus.DONE)


async def test_two_guests_start_together_and_the_third_analysis_starts_when_its_guest_frees(
    parallel_runner: Runner, session_factory: Factory, cape: FakeCape
) -> None:
    first_on_lab3 = await enqueue(session_factory, options=on("lab3"))
    second_on_lab3 = await enqueue(session_factory, options=on("lab3"))
    on_lab5 = await enqueue(session_factory, options=on("lab5"))

    await parallel_runner.run_once()

    assert [task["machine"] for task in cape.created] == ["lab3", "lab5"]
    assert (await load(session_factory, first_on_lab3)).status is AnalysisStatus.STARTING
    assert (await load(session_factory, on_lab5)).status is AnalysisStatus.STARTING
    assert (await load(session_factory, second_on_lab3)).status is AnalysisStatus.QUEUED

    await end(session_factory, first_on_lab3)
    await parallel_runner.run_once()

    assert [task["machine"] for task in cape.created] == ["lab3", "lab5", "lab3"]
    assert (await load(session_factory, second_on_lab3)).status is AnalysisStatus.STARTING


async def test_a_queued_analysis_behind_a_busy_guest_does_not_hold_up_an_idle_guests(
    parallel_runner: Runner, session_factory: Factory, cape: FakeCape
) -> None:
    cape.scripts[7] = ["running"]
    await adopt_by_cape(
        session_factory, 7, AnalysisStatus.RUNNING, options=on("lab3"), started_at=STARTED
    )
    waiting = await enqueue(session_factory, options=on("lab3"))
    idle = await enqueue(session_factory, options=on("lab5"))

    await parallel_runner.run_once()

    assert [task["machine"] for task in cape.created] == ["lab5"]
    assert (await load(session_factory, idle)).status is AnalysisStatus.STARTING
    assert (await load(session_factory, waiting)).status is AnalysisStatus.QUEUED


async def test_every_active_analysis_is_followed_in_the_same_pass(
    parallel_runner: Runner, session_factory: Factory, cape: FakeCape
) -> None:
    cape.scripts[7] = ["running"]
    cape.scripts[8] = ["running"]
    on_lab3 = await adopt_by_cape(session_factory, 7, options=on("lab3"))
    on_lab5 = await adopt_by_cape(session_factory, 8, options=on("lab5"))

    await parallel_runner.run_once()

    assert (await load(session_factory, on_lab3)).status is AnalysisStatus.RUNNING
    assert (await load(session_factory, on_lab5)).status is AnalysisStatus.RUNNING


async def test_a_slow_ingest_of_one_analysis_does_not_move_the_deadline_of_another(  # noqa: PLR0913, PLR0917
    parallel_runner: Runner,
    session_factory: Factory,
    cape: FakeCape,
    reports: FakeReports,
    gated_ingester: GatedIngester,
    guests: AnnouncingGuestControl,
    wall_clock: WallClock,
) -> None:
    reports.outcome = OUTCOME
    cape.scripts[7] = ["reported"]
    cape.scripts[8] = ["running"]
    ingested = await adopt_by_cape(session_factory, 7, options=on("lab3"))
    await adopt_by_cape(
        session_factory,
        8,
        AnalysisStatus.RUNNING,
        options=on("lab5", interactive=True),
        started_at=STARTED,
        deadline_at=at(100),
    )
    parallel_runner.start()
    try:
        await asyncio.wait_for(gated_ingester.began.wait(), PATIENCE_SECONDS)
        assert guests.finished == []

        wall_clock.now = at(101)
        parallel_runner.nudge()
        await asyncio.wait_for(guests.finish_asked.wait(), PATIENCE_SECONDS)

        assert guests.finished == [(8, "lab5")]
        assert (await load(session_factory, ingested)).status is AnalysisStatus.INGESTING
    finally:
        gated_ingester.release.set()
        await parallel_runner.stop()
    assert (await load(session_factory, ingested)).status is AnalysisStatus.DONE


async def test_two_runs_are_collected_live_at_once_and_ending_one_leaves_the_other(
    parallel_runner: Runner, session_factory: Factory, cape: FakeCape, live: FakeLive
) -> None:
    cape.scripts[7] = ["running", "completed"]
    cape.scripts[8] = ["running"]
    on_lab3 = await adopt_by_cape(
        session_factory, 7, AnalysisStatus.RUNNING, options=on("lab3"), started_at=STARTED
    )
    on_lab5 = await adopt_by_cape(
        session_factory, 8, AnalysisStatus.RUNNING, options=on("lab5"), started_at=STARTED
    )

    await parallel_runner.run_once()
    await parallel_runner.run_once()

    assert sorted(analysis_id for analysis_id, _, _ in live.started) == [on_lab3, on_lab5]
    assert live.stopped == [on_lab3]
