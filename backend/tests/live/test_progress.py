from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db import analysis_repository as repository
from app.db.models.analysis import AnalysisPhase, AnalysisStatus
from app.live.messages import StatusData
from app.live.progress import DbProgressSource, is_finished
from tests.analyses.helpers import enqueue

type Factory = async_sessionmaker[AsyncSession]

STARTED = datetime(2026, 10, 13, 12, 0, 0, tzinfo=UTC)
TIMEOUT_S = 180


class Clock:
    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


@pytest.fixture
def clock() -> Clock:
    return Clock(STARTED + timedelta(seconds=30))


@pytest.fixture
def source(session_factory: Factory, clock: Clock) -> DbProgressSource:
    return DbProgressSource(session_factory, clock=clock)


async def analysis_with(session_factory: Factory, **changes: object) -> int:
    analysis_id = await enqueue(
        session_factory, options={"route": "inetsim", "timeout": TIMEOUT_S, "package": "auto"}
    )
    async with session_factory() as session:
        await repository.update_analysis(session, analysis_id, **changes)  # type: ignore[arg-type]
    return analysis_id


async def test_an_unknown_analysis_has_no_progress(source: DbProgressSource) -> None:
    assert await source.read(404) is None


async def test_a_queued_analysis_has_no_clock_yet(
    source: DbProgressSource, session_factory: Factory
) -> None:
    analysis_id = await enqueue(session_factory)

    assert await source.read(analysis_id) == StatusData(
        status=AnalysisStatus.QUEUED, phase=AnalysisPhase.LIVE, elapsed_s=None, remaining_s=None
    )


async def test_a_running_analysis_counts_up_from_its_start_and_down_to_its_timeout(
    source: DbProgressSource, session_factory: Factory
) -> None:
    analysis_id = await analysis_with(
        session_factory, status=AnalysisStatus.RUNNING, started_at=STARTED
    )

    progress = await source.read(analysis_id)

    assert progress == StatusData(
        status=AnalysisStatus.RUNNING,
        phase=AnalysisPhase.LIVE,
        elapsed_s=30.0,
        remaining_s=TIMEOUT_S - 30.0,
    )


async def test_the_remaining_time_never_goes_below_zero(
    source: DbProgressSource, session_factory: Factory, clock: Clock
) -> None:
    analysis_id = await analysis_with(
        session_factory, status=AnalysisStatus.PROCESSING, started_at=STARTED
    )
    clock.now = STARTED + timedelta(seconds=TIMEOUT_S + 50)

    progress = await source.read(analysis_id)

    assert progress is not None
    assert (progress.elapsed_s, progress.remaining_s) == (TIMEOUT_S + 50.0, 0.0)


async def test_a_finished_analysis_reports_its_run_time_and_nothing_remaining(
    source: DbProgressSource, session_factory: Factory
) -> None:
    analysis_id = await analysis_with(
        session_factory,
        status=AnalysisStatus.DONE,
        phase=AnalysisPhase.FINAL,
        started_at=STARTED,
        finished_at=STARTED + timedelta(seconds=95),
    )

    progress = await source.read(analysis_id)

    assert progress == StatusData(
        status=AnalysisStatus.DONE, phase=AnalysisPhase.FINAL, elapsed_s=95.0, remaining_s=0.0
    )


async def test_a_start_time_without_a_zone_is_read_as_utc(
    source: DbProgressSource, session_factory: Factory
) -> None:
    analysis_id = await analysis_with(
        session_factory,
        status=AnalysisStatus.RUNNING,
        started_at=STARTED.replace(tzinfo=None),
    )

    progress = await source.read(analysis_id)

    assert progress is not None
    assert progress.elapsed_s == 30.0


@pytest.mark.parametrize(
    ("status", "finished"),
    [
        (AnalysisStatus.QUEUED, False),
        (AnalysisStatus.STARTING, False),
        (AnalysisStatus.RUNNING, False),
        (AnalysisStatus.PROCESSING, False),
        (AnalysisStatus.INGESTING, False),
        (AnalysisStatus.DONE, True),
        (AnalysisStatus.FAILED, True),
        (AnalysisStatus.REPORT_FAILED, True),
        (AnalysisStatus.CANCELLED, True),
    ],
)
def test_an_analysis_is_finished_once_it_is_done_failed_or_cancelled(
    status: AnalysisStatus, finished: bool
) -> None:
    assert is_finished(status) is finished
