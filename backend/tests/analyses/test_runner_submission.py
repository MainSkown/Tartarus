import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.analyses import runner as runner_module
from app.analyses.runner import Runner
from app.cape.errors import CapeAuthError, CapeBadResponse, CapeRejected, CapeUnreachable
from app.db import analysis_repository as repository
from app.db.models.analysis import AnalysisStatus
from tests.analyses.fakes import FakeCape, FakeSamples
from tests.analyses.helpers import enqueue, load
from tests.test_analysis_repository import SHA_B

type Factory = async_sessionmaker[AsyncSession]


async def test_nothing_happens_while_there_is_nothing_to_do(runner: Runner, cape: FakeCape) -> None:
    await runner.run_once()

    assert cape.calls == []


async def test_the_oldest_queued_analysis_is_uploaded_with_its_options(
    runner: Runner, session_factory: Factory, cape: FakeCape, samples: FakeSamples
) -> None:
    options = {"route": "none", "timeout": 300, "package": "exe"}
    analysis_id = await enqueue(session_factory, "dropper.exe", SHA_B, options)

    await runner.run_once()

    assert cape.created == [
        {
            "task_id": 100,
            "filename": "dropper.exe",
            "machine": "win",
            "route": "none",
            "timeout": 300,
            "package": "exe",
            "options": "",
            "task_fields": {},
        }
    ]
    assert samples.opened == [SHA_B]
    assert samples.open_now == 0
    assert cape.uploaded_bytes == [b"MZ plain sample"]
    submitted = await load(session_factory, analysis_id)
    assert submitted.status is AnalysisStatus.STARTING
    assert submitted.cape_task_id == 100


async def test_the_package_defaults_to_auto(
    runner: Runner, session_factory: Factory, cape: FakeCape
) -> None:
    await enqueue(session_factory, options={"route": "inetsim", "timeout": 120})

    await runner.run_once()

    assert cape.created[0]["package"] == "auto"


async def test_two_queued_analyses_run_one_after_the_other_in_order(
    runner: Runner, session_factory: Factory, cape: FakeCape
) -> None:
    cape.script_for_new_tasks = ["running", "failed_analysis"]
    first = await enqueue(session_factory, "first.exe")
    second = await enqueue(session_factory, "second.exe")

    def creates() -> list[tuple[str, object]]:
        return [call for call in cape.calls if call[0] == "create"]

    await runner.run_once()
    await runner.run_once()
    assert creates() == [("create", "first.exe")]
    assert (await load(session_factory, second)).status is AnalysisStatus.QUEUED

    await runner.run_once()
    assert (await load(session_factory, first)).status is AnalysisStatus.FAILED
    assert (await load(session_factory, second)).status is AnalysisStatus.QUEUED

    await runner.run_once()
    assert creates() == [("create", "first.exe"), ("create", "second.exe")]
    assert (await load(session_factory, second)).cape_task_id == 101


async def test_an_analysis_cancelled_during_the_claim_is_skipped_for_the_next_one(
    runner: Runner,
    session_factory: Factory,
    cape: FakeCape,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cancelled = await enqueue(session_factory, "cancelled.exe")
    waiting = await enqueue(session_factory, "waiting.exe")
    real_claim = runner_module.claim_queued

    async def claim_after_a_cancel(session: AsyncSession, analysis_id: int) -> bool:
        await repository.cancel_if_queued(session, cancelled)
        return await real_claim(session, analysis_id)

    monkeypatch.setattr(runner_module, "claim_queued", claim_after_a_cancel)
    await runner.run_once()

    assert (await load(session_factory, cancelled)).status is AnalysisStatus.CANCELLED
    assert (await load(session_factory, cancelled)).cape_task_id is None
    assert cape.calls == [("create", "waiting.exe")]
    assert (await load(session_factory, waiting)).status is AnalysisStatus.STARTING


async def test_cape_being_unreachable_at_submit_puts_the_analysis_back_in_the_queue(
    runner: Runner, session_factory: Factory, cape: FakeCape
) -> None:
    cape.create_errors = [CapeUnreachable("tasks/create/file", "ConnectError")]
    analysis_id = await enqueue(session_factory)

    await runner.run_once()

    waiting = await load(session_factory, analysis_id)
    assert waiting.status is AnalysisStatus.QUEUED
    assert waiting.cape_task_id is None
    assert waiting.error is None

    await runner.run_once()

    assert (await load(session_factory, analysis_id)).cape_task_id == 100


async def test_a_task_cape_refuses_fails_the_analysis_with_cape_s_message(
    runner: Runner, session_factory: Factory, cape: FakeCape
) -> None:
    cape.create_errors = [CapeRejected("tasks/create/file", "File type not supported")]
    analysis_id = await enqueue(session_factory)

    await runner.run_once()

    failed = await load(session_factory, analysis_id)
    assert failed.status is AnalysisStatus.FAILED
    assert failed.error == "CAPE refused the task: File type not supported"
    assert failed.finished_at is not None


async def test_a_refused_token_at_submit_fails_the_analysis_and_names_the_token(
    runner: Runner, session_factory: Factory, cape: FakeCape
) -> None:
    cape.create_errors = [CapeAuthError("tasks/create/file")]
    analysis_id = await enqueue(session_factory)

    await runner.run_once()

    failed = await load(session_factory, analysis_id)
    assert failed.status is AnalysisStatus.FAILED
    assert failed.error is not None
    assert "token" in failed.error.lower()


async def test_an_answer_cape_does_not_make_sense_of_fails_the_analysis_without_a_retry(
    runner: Runner, session_factory: Factory, cape: FakeCape
) -> None:
    cape.create_errors = [CapeBadResponse("tasks/create/file", "no task id in the answer")]
    analysis_id = await enqueue(session_factory)

    await runner.run_once()

    failed = await load(session_factory, analysis_id)
    assert failed.status is AnalysisStatus.FAILED
    assert failed.error is not None
    assert "no task id" in failed.error


async def test_a_missing_sample_file_fails_the_analysis(
    runner: Runner, session_factory: Factory, cape: FakeCape, samples: FakeSamples
) -> None:
    samples.missing = True
    analysis_id = await enqueue(session_factory)

    await runner.run_once()

    failed = await load(session_factory, analysis_id)
    assert failed.status is AnalysisStatus.FAILED
    assert failed.error is not None
    assert "sample" in failed.error
    assert cape.calls == []


async def test_an_unexpected_error_at_submit_never_leaves_the_analysis_starting(
    runner: Runner, session_factory: Factory, cape: FakeCape
) -> None:
    cape.create_errors = [RuntimeError("boom")]
    analysis_id = await enqueue(session_factory)

    await runner.run_once()

    failed = await load(session_factory, analysis_id)
    assert failed.status is AnalysisStatus.FAILED
    assert failed.error is not None
    assert "RuntimeError" in failed.error
