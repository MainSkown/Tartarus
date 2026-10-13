import logging

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.analyses.runner import MAX_CONSECUTIVE_ERRORS, Runner
from app.cape.errors import (
    CapeAuthError,
    CapeBadResponse,
    CapeNotConfigured,
    CapeTaskNotFound,
    CapeUnreachable,
)
from app.db.models.analysis import AnalysisStatus
from tests.analyses.conftest import GRACE_SECONDS
from tests.analyses.fakes import FakeCape, FakeClock
from tests.analyses.helpers import adopt_by_cape, load

type Factory = async_sessionmaker[AsyncSession]

UNREACHABLE = CapeUnreachable("tasks/status", "ConnectError")


async def test_a_short_outage_changes_nothing_and_tracking_continues_afterwards(
    runner: Runner, session_factory: Factory, cape: FakeCape, clock: FakeClock
) -> None:
    cape.scripts[7] = [UNREACHABLE, UNREACHABLE, "running"]
    analysis_id = await adopt_by_cape(session_factory, 7)

    await runner.run_once()
    clock.advance(30)
    await runner.run_once()
    assert (await load(session_factory, analysis_id)).status is AnalysisStatus.STARTING

    clock.advance(30)
    await runner.run_once()

    assert (await load(session_factory, analysis_id)).status is AnalysisStatus.RUNNING


async def test_an_outage_longer_than_the_grace_period_fails_the_analysis(
    runner: Runner, session_factory: Factory, cape: FakeCape, clock: FakeClock
) -> None:
    cape.scripts[7] = [UNREACHABLE]
    analysis_id = await adopt_by_cape(session_factory, 7, AnalysisStatus.RUNNING)

    await runner.run_once()
    clock.advance(GRACE_SECONDS + 1)
    await runner.run_once()

    failed = await load(session_factory, analysis_id)
    assert failed.status is AnalysisStatus.FAILED
    assert failed.error == "CAPE has been unreachable for 121 seconds"
    assert failed.finished_at is not None


async def test_an_outage_exactly_as_long_as_the_grace_period_is_still_tolerated(
    runner: Runner, session_factory: Factory, cape: FakeCape, clock: FakeClock
) -> None:
    cape.scripts[7] = [UNREACHABLE]
    analysis_id = await adopt_by_cape(session_factory, 7)

    await runner.run_once()
    clock.advance(GRACE_SECONDS)
    await runner.run_once()

    assert (await load(session_factory, analysis_id)).status is AnalysisStatus.STARTING


async def test_a_successful_call_resets_the_outage_clock(
    runner: Runner, session_factory: Factory, cape: FakeCape, clock: FakeClock
) -> None:
    cape.scripts[7] = [UNREACHABLE, "running", UNREACHABLE, UNREACHABLE]
    analysis_id = await adopt_by_cape(session_factory, 7)

    await runner.run_once()
    clock.advance(100)
    await runner.run_once()
    await runner.run_once()
    clock.advance(100)
    await runner.run_once()

    assert (await load(session_factory, analysis_id)).status is AnalysisStatus.RUNNING


async def test_a_task_cape_no_longer_knows_fails_the_analysis(
    runner: Runner, session_factory: Factory, cape: FakeCape
) -> None:
    cape.scripts[7] = [CapeTaskNotFound("tasks/status", 7, "Task does not exist")]
    analysis_id = await adopt_by_cape(session_factory, 7, AnalysisStatus.RUNNING)

    await runner.run_once()

    failed = await load(session_factory, analysis_id)
    assert failed.status is AnalysisStatus.FAILED
    assert failed.error == "CAPE no longer knows task 7"


@pytest.mark.parametrize("refusal", [CapeAuthError("tasks/status"), CapeNotConfigured()])
async def test_a_refused_or_missing_token_fails_the_analysis_and_names_the_token(
    runner: Runner, session_factory: Factory, cape: FakeCape, refusal: Exception
) -> None:
    cape.scripts[7] = [refusal]
    analysis_id = await adopt_by_cape(session_factory, 7, AnalysisStatus.RUNNING)

    await runner.run_once()

    failed = await load(session_factory, analysis_id)
    assert failed.status is AnalysisStatus.FAILED
    assert failed.error is not None
    assert "token" in failed.error.lower()


async def test_an_unknown_cape_status_changes_nothing_and_is_logged(
    runner: Runner,
    session_factory: Factory,
    cape: FakeCape,
    caplog: pytest.LogCaptureFixture,
) -> None:
    cape.scripts[7] = ["quantum_superposition"]
    analysis_id = await adopt_by_cape(session_factory, 7, AnalysisStatus.RUNNING)

    with caplog.at_level(logging.WARNING):
        await runner.run_once()

    assert (await load(session_factory, analysis_id)).status is AnalysisStatus.RUNNING
    assert "quantum_superposition" in caplog.text


async def test_an_unknown_cape_status_that_lasts_past_the_grace_period_fails_the_analysis(
    runner: Runner, session_factory: Factory, cape: FakeCape, clock: FakeClock
) -> None:
    cape.scripts[7] = ["quantum_superposition"]
    analysis_id = await adopt_by_cape(session_factory, 7, AnalysisStatus.RUNNING)

    await runner.run_once()
    clock.advance(GRACE_SECONDS + 1)
    await runner.run_once()

    failed = await load(session_factory, analysis_id)
    assert failed.status is AnalysisStatus.FAILED
    assert failed.error is not None
    assert "quantum_superposition" in failed.error


async def test_any_other_cape_error_counts_like_an_outage(
    runner: Runner, session_factory: Factory, cape: FakeCape, clock: FakeClock
) -> None:
    cape.scripts[7] = [CapeBadResponse("tasks/status", "body is not JSON")]
    analysis_id = await adopt_by_cape(session_factory, 7, AnalysisStatus.RUNNING)

    await runner.run_once()
    assert (await load(session_factory, analysis_id)).status is AnalysisStatus.RUNNING
    clock.advance(GRACE_SECONDS + 1)
    await runner.run_once()

    failed = await load(session_factory, analysis_id)
    assert failed.status is AnalysisStatus.FAILED
    assert failed.error is not None
    assert "body is not JSON" in failed.error


async def test_an_unexpected_error_leaves_the_analysis_for_the_next_tick(
    runner: Runner, session_factory: Factory, cape: FakeCape
) -> None:
    cape.scripts[7] = [RuntimeError("boom"), "running"]
    analysis_id = await adopt_by_cape(session_factory, 7)

    await runner.run_once()
    assert (await load(session_factory, analysis_id)).status is AnalysisStatus.STARTING
    await runner.run_once()

    assert (await load(session_factory, analysis_id)).status is AnalysisStatus.RUNNING


async def test_an_analysis_that_keeps_raising_unexpected_errors_is_failed(
    runner: Runner, session_factory: Factory, cape: FakeCape
) -> None:
    cape.scripts[7] = [RuntimeError("boom")]
    analysis_id = await adopt_by_cape(session_factory, 7)

    for _ in range(MAX_CONSECUTIVE_ERRORS - 1):
        await runner.run_once()
    assert (await load(session_factory, analysis_id)).status is AnalysisStatus.STARTING
    await runner.run_once()

    failed = await load(session_factory, analysis_id)
    assert failed.status is AnalysisStatus.FAILED
    assert failed.error is not None
    assert "RuntimeError" in failed.error


async def test_unexpected_errors_that_are_not_consecutive_do_not_add_up(
    runner: Runner, session_factory: Factory, cape: FakeCape
) -> None:
    boom = RuntimeError("boom")
    cape.scripts[7] = [boom, boom, "pending", boom, boom, "pending"]
    analysis_id = await adopt_by_cape(session_factory, 7)

    for _ in range(6):
        await runner.run_once()

    assert (await load(session_factory, analysis_id)).status is AnalysisStatus.STARTING
