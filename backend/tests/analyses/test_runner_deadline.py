import os
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.analyses.runner import Runner, RunnerConfig
from app.db import analysis_repository as repository
from app.db.models.analysis import AnalysisStatus
from app.guest.errors import GuestControlRejected, GuestControlUnreachable
from tests.analyses.conftest import GRACE_SECONDS
from tests.analyses.fakes import FakeCape, FakeIngester, FakeReports, FakeSamples
from tests.analyses.guest_fakes import ScriptedGuestControl
from tests.analyses.helpers import as_utc, enqueue, load

type Factory = async_sessionmaker[AsyncSession]

STARTED = datetime(2026, 10, 17, 9, 0, 0, tzinfo=UTC)
INTERACTIVE = {"route": "inetsim", "timeout": 180, "package": "auto", "interactive": True}
NOT_INTERACTIVE = {"route": "inetsim", "timeout": 180, "package": "auto"}


def at(seconds: float) -> datetime:
    return STARTED + timedelta(seconds=seconds)


class WallClock:
    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


def write_monitor_log(storage: Path, task_id: int, name: str, seen_at: datetime) -> None:
    logs = storage / "analyses" / str(task_id) / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    log = logs / name
    log.write_bytes(b"\x05\x00\x00\x00\x00")
    os.utime(log, (seen_at.timestamp(), seen_at.timestamp()))


async def running_analysis(
    session_factory: Factory,
    options: dict[str, object] = INTERACTIVE,
    *,
    deadline_at: datetime | None = None,
) -> int:
    analysis_id = await enqueue(session_factory, options=options)
    async with session_factory() as session:
        await repository.update_analysis(
            session,
            analysis_id,
            status=AnalysisStatus.RUNNING,
            cape_task_id=7,
            started_at=STARTED,
            deadline_at=deadline_at,
        )
    return analysis_id


@pytest.fixture
def storage(tmp_path: Path) -> Path:
    return tmp_path / "cape"


@pytest.fixture
def wall_clock() -> WallClock:
    return WallClock(at(10))


@pytest.fixture
def make_deadline_runner(  # noqa: PLR0913, PLR0917 - a fixture assembling every fake
    session_factory: Factory,
    cape: FakeCape,
    samples: FakeSamples,
    reports: FakeReports,
    ingester: FakeIngester,
    guests: ScriptedGuestControl,
    storage: Path,
    wall_clock: WallClock,
) -> Callable[[], Runner]:
    config = RunnerConfig(
        cape_storage_path=storage, poll_interval=3600.0, unreachable_grace=GRACE_SECONDS
    )

    def build() -> Runner:
        return Runner(
            session_factory,
            cape,
            samples,
            reports,
            ingester,
            guests,
            config,
            now=wall_clock,
        )

    return build


async def test_the_deadline_counts_the_timeout_from_the_oldest_monitor_log(
    make_deadline_runner: Callable[[], Runner],
    session_factory: Factory,
    cape: FakeCape,
    storage: Path,
) -> None:
    cape.scripts[7] = ["running"]
    analysis_id = await running_analysis(session_factory)
    write_monitor_log(storage, 7, "1234.bson", at(40))
    write_monitor_log(storage, 7, "5678.bson", at(25))

    await make_deadline_runner().run_once()

    deadline = (await load(session_factory, analysis_id)).deadline_at
    assert as_utc(deadline) == at(25 + 180)


async def test_the_deadline_is_capped_at_twenty_minutes_after_the_start(
    make_deadline_runner: Callable[[], Runner],
    session_factory: Factory,
    cape: FakeCape,
    storage: Path,
) -> None:
    cape.scripts[7] = ["running"]
    analysis_id = await running_analysis(session_factory, {**INTERACTIVE, "timeout": 1200})
    write_monitor_log(storage, 7, "1234.bson", at(25))

    await make_deadline_runner().run_once()

    deadline = (await load(session_factory, analysis_id)).deadline_at
    assert as_utc(deadline) == at(1200)


async def test_no_deadline_is_set_before_the_monitor_has_written_a_log(
    make_deadline_runner: Callable[[], Runner],
    session_factory: Factory,
    cape: FakeCape,
    guests: ScriptedGuestControl,
) -> None:
    cape.scripts[7] = ["running"]
    analysis_id = await running_analysis(session_factory)

    await make_deadline_runner().run_once()

    assert (await load(session_factory, analysis_id)).deadline_at is None
    assert guests.finished == []


async def test_nothing_is_ended_before_the_deadline(
    make_deadline_runner: Callable[[], Runner],
    session_factory: Factory,
    cape: FakeCape,
    guests: ScriptedGuestControl,
    wall_clock: WallClock,
) -> None:
    cape.scripts[7] = ["running"]
    analysis_id = await running_analysis(session_factory, deadline_at=at(100))
    wall_clock.now = at(50)

    await make_deadline_runner().run_once()

    assert guests.finished == []
    assert (await load(session_factory, analysis_id)).status is AnalysisStatus.RUNNING


async def test_a_run_past_its_deadline_is_asked_to_end_once_per_poll(
    make_deadline_runner: Callable[[], Runner],
    session_factory: Factory,
    cape: FakeCape,
    guests: ScriptedGuestControl,
    wall_clock: WallClock,
) -> None:
    cape.scripts[7] = ["running"]
    analysis_id = await running_analysis(session_factory, deadline_at=at(100))
    wall_clock.now = at(101)
    runner = make_deadline_runner()

    await runner.run_once()
    await runner.run_once()

    assert guests.finished == [(7, "win"), (7, "win")]
    assert (await load(session_factory, analysis_id)).status is AnalysisStatus.RUNNING


@pytest.mark.parametrize(
    "refusal",
    [
        GuestControlUnreachable("finish_task", "ConnectError"),
        GuestControlRejected("finish_task", 502, "the guest agent is unreachable (URLError)"),
    ],
    ids=["unreachable", "rejected"],
)
async def test_a_failed_end_request_leaves_the_run_running_and_is_retried(  # noqa: PLR0913, PLR0917 - the fakes and the clock a run needs
    make_deadline_runner: Callable[[], Runner],
    session_factory: Factory,
    cape: FakeCape,
    guests: ScriptedGuestControl,
    wall_clock: WallClock,
    refusal: Exception,
) -> None:
    cape.scripts[7] = ["running"]
    analysis_id = await running_analysis(session_factory, deadline_at=at(100))
    wall_clock.now = at(101)
    guests.finish_error = refusal
    runner = make_deadline_runner()

    for _ in range(3):
        await runner.run_once()
    assert (await load(session_factory, analysis_id)).status is AnalysisStatus.RUNNING

    guests.finish_error = None
    await runner.run_once()

    assert guests.finished == [(7, "win")]
    assert (await load(session_factory, analysis_id)).status is AnalysisStatus.RUNNING


async def test_a_new_runner_ends_the_run_at_the_deadline_the_dead_one_set(  # noqa: PLR0913, PLR0917 - the fakes and the clock a run needs
    make_deadline_runner: Callable[[], Runner],
    session_factory: Factory,
    cape: FakeCape,
    guests: ScriptedGuestControl,
    storage: Path,
    wall_clock: WallClock,
) -> None:
    cape.scripts[7] = ["running"]
    analysis_id = await running_analysis(session_factory)
    write_monitor_log(storage, 7, "1234.bson", at(25))
    await make_deadline_runner().run_once()
    wall_clock.now = at(206)

    await make_deadline_runner().run_once()

    assert guests.finished == [(7, "win")]
    assert as_utc((await load(session_factory, analysis_id)).deadline_at) == at(205)


async def test_a_non_interactive_run_never_gets_a_deadline_and_is_never_ended(  # noqa: PLR0913, PLR0917 - the fakes and the clock a run needs
    make_deadline_runner: Callable[[], Runner],
    session_factory: Factory,
    cape: FakeCape,
    guests: ScriptedGuestControl,
    storage: Path,
    wall_clock: WallClock,
) -> None:
    cape.scripts[7] = ["running"]
    analysis_id = await running_analysis(session_factory, NOT_INTERACTIVE)
    write_monitor_log(storage, 7, "1234.bson", at(25))
    wall_clock.now = at(5000)

    await make_deadline_runner().run_once()

    analysis = await load(session_factory, analysis_id)
    assert analysis.deadline_at is None
    assert analysis.status is AnalysisStatus.RUNNING
    assert guests.finished == []
