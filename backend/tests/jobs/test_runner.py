import asyncio
import threading
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db import job_repository as repository
from app.db.models import Job
from app.db.models.job import JobStatus, JobType
from app.jobs.runner import JobContext, JobRunner
from app.ws.messages import JobMessage
from tests.test_analysis_repository import seeded_analysis

TIMEOUT_S = 5.0
JOB_TYPE = JobType.EXPORT_REPORT

type SessionFactory = async_sessionmaker[AsyncSession]


@pytest.fixture
async def runner(session_factory: SessionFactory, tmp_path: Path) -> AsyncIterator[JobRunner]:
    job_runner = JobRunner(session_factory, tmp_path / "exports")
    await job_runner.start()
    yield job_runner
    await job_runner.stop()


async def stored(factory: SessionFactory, job_id: int) -> Job:
    async with factory() as session:
        job = await repository.get_job(session, job_id)
    assert job is not None
    return job


async def wait_for(factory: SessionFactory, job_id: int) -> Job:
    """Waits until the job has ended."""
    ended = (JobStatus.DONE, JobStatus.FAILED, JobStatus.INTERRUPTED)
    return await wait_until(factory, job_id, lambda job: job.status in ended)


async def wait_until(factory: SessionFactory, job_id: int, check: Callable[[Job], bool]) -> Job:
    async def poll() -> Job:
        while True:
            job = await stored(factory, job_id)
            if check(job):
                return job
            await asyncio.sleep(0.005)

    return await asyncio.wait_for(poll(), TIMEOUT_S)


async def test_a_submitted_job_is_stored_pending_before_anything_runs(
    session_factory: SessionFactory, tmp_path: Path
) -> None:
    idle_runner = JobRunner(session_factory, tmp_path)

    job = await idle_runner.submit(JOB_TYPE, None, {"format": "pdf"})

    assert (await stored(session_factory, job.id)).status is JobStatus.PENDING


async def test_an_async_handler_runs_and_its_result_is_stored(
    runner: JobRunner, session_factory: SessionFactory
) -> None:
    async def handler(context: JobContext) -> dict[str, Any]:
        return {"echo": dict(context.params)}

    runner.register(JOB_TYPE, handler)

    job = await runner.submit(JOB_TYPE, None, {"format": "pdf"})
    done = await wait_for(session_factory, job.id)

    assert (done.status, done.progress, done.result) == (
        JobStatus.DONE,
        100,
        {"echo": {"format": "pdf"}},
    )


async def test_a_sync_handler_runs_off_the_event_loop(
    runner: JobRunner, session_factory: SessionFactory
) -> None:
    def handler(_: JobContext) -> dict[str, Any]:
        return {"thread": threading.get_ident()}

    runner.register(JOB_TYPE, handler)

    job = await runner.submit(JOB_TYPE, None, {})
    done = await wait_for(session_factory, job.id)

    assert done.status is JobStatus.DONE
    assert done.result is not None
    assert done.result["thread"] != threading.get_ident()


async def test_the_handler_is_given_its_analysis_and_the_exports_directory(
    runner: JobRunner, session_factory: SessionFactory, tmp_path: Path
) -> None:
    async def handler(context: JobContext) -> dict[str, Any]:
        return {
            "analysis_id": context.analysis_id,
            "exports_dir": str(context.exports_dir),
            "analysis_dir": str(context.analysis_dir()),
        }

    runner.register(JOB_TYPE, handler)
    async with session_factory() as session:
        analysis = await seeded_analysis(session)

    job = await runner.submit(JOB_TYPE, analysis.id, {})
    done = await wait_for(session_factory, job.id)

    assert done.result == {
        "analysis_id": analysis.id,
        "exports_dir": str(tmp_path / "exports"),
        "analysis_dir": str(tmp_path / "exports" / str(analysis.id)),
    }
    assert (tmp_path / "exports" / str(analysis.id)).is_dir()


async def test_a_job_without_an_analysis_has_no_analysis_directory(
    runner: JobRunner, session_factory: SessionFactory
) -> None:
    def handler(context: JobContext) -> dict[str, Any]:
        return {"dir": str(context.analysis_dir())}

    runner.register(JobType.GUEST_BUILD, handler)

    job = await runner.submit(JobType.GUEST_BUILD, None, {})
    done = await wait_for(session_factory, job.id)

    assert done.status is JobStatus.FAILED


async def test_progress_is_persisted_while_the_handler_is_still_running(
    runner: JobRunner, session_factory: SessionFactory
) -> None:
    release = asyncio.Event()

    async def handler(context: JobContext) -> dict[str, Any]:
        context.report_progress("Rendering", 40)
        await release.wait()
        return {}

    runner.register(JOB_TYPE, handler)

    job = await runner.submit(JOB_TYPE, None, {})
    midway = await wait_until(session_factory, job.id, lambda row: row.progress == 40)
    release.set()
    done = await wait_for(session_factory, job.id)

    assert (midway.status, midway.step, midway.log) == (
        JobStatus.RUNNING,
        "Rendering",
        "40% Rendering",
    )
    assert (done.status, done.progress) == (JobStatus.DONE, 100)


async def test_a_sync_handler_reports_progress_from_its_thread_in_order(
    runner: JobRunner, session_factory: SessionFactory
) -> None:
    def handler(context: JobContext) -> dict[str, Any]:
        for percent in range(1, 21):
            context.report_progress(f"step {percent}", percent)
        return {}

    runner.register(JOB_TYPE, handler)

    job = await runner.submit(JOB_TYPE, None, {})
    done = await wait_for(session_factory, job.id)

    assert done.log.splitlines()[-1] == "20% step 20"
    assert [line.split()[0] for line in done.log.splitlines()] == [
        f"{percent}%" for percent in range(1, 21)
    ]


@pytest.mark.parametrize(("reported", "stored_percent"), [(-5, 0), (250, 100)])
async def test_a_percentage_outside_the_range_is_clamped(
    runner: JobRunner, session_factory: SessionFactory, reported: int, stored_percent: int
) -> None:
    release = asyncio.Event()

    async def handler(context: JobContext) -> dict[str, Any]:
        context.report_progress("Odd", reported)
        await release.wait()
        return {}

    runner.register(JOB_TYPE, handler)

    job = await runner.submit(JOB_TYPE, None, {})
    midway = await wait_until(session_factory, job.id, lambda row: row.step == "Odd")
    release.set()

    assert midway.progress == stored_percent


async def test_a_handler_can_append_to_the_log_and_pause_and_resume_its_job(
    runner: JobRunner, session_factory: SessionFactory
) -> None:
    release = asyncio.Event()

    async def handler(context: JobContext) -> dict[str, Any]:
        context.report_progress("Installing", 30)
        context.append_log("STEP install\nSTEP provision")
        context.pause("Switch it off by hand")
        await release.wait()
        context.resume()
        context.report_progress("Provisioning", 60)
        await release.wait()
        return {"state": "testing"}

    runner.register(JOB_TYPE, handler)
    with runner.feed.subscribe() as subscription:
        job = await runner.submit(JOB_TYPE, None, {})
        paused = await wait_until(
            session_factory, job.id, lambda row: row.status is JobStatus.PAUSED
        )
        release.set()
        done = await wait_for(session_factory, job.id)
        seen = [subscription.inbox.get_nowait() for _ in range(subscription.inbox.qsize())]

    assert paused.result == {"pause": {"instructions": "Switch it off by hand"}}
    assert paused.log.splitlines() == ["30% Installing", "STEP install", "STEP provision"]
    assert [(m.job.status, m.job.progress, m.job.result) for m in seen][-4:] == [
        (JobStatus.PAUSED, 30, {"pause": {"instructions": "Switch it off by hand"}}),
        (JobStatus.RUNNING, 30, None),
        (JobStatus.RUNNING, 60, None),
        (JobStatus.DONE, 100, {"state": "testing"}),
    ]
    assert done.result == {"state": "testing"}


async def test_a_paused_job_is_active_for_a_client_that_connects_mid_pause(
    runner: JobRunner, session_factory: SessionFactory
) -> None:
    release = asyncio.Event()

    async def handler(context: JobContext) -> dict[str, Any]:
        context.pause("Wait for it")
        await release.wait()
        return {}

    runner.register(JOB_TYPE, handler)
    job = await runner.submit(JOB_TYPE, None, {})
    await wait_until(session_factory, job.id, lambda row: row.status is JobStatus.PAUSED)

    with runner.feed.subscribe() as subscription:
        release.set()
        await wait_for(session_factory, job.id)

    assert [(m.job.id, m.job.status) for m in subscription.snapshot] == [(job.id, JobStatus.PAUSED)]


async def test_a_sync_handler_pauses_and_logs_from_its_thread_in_order(
    runner: JobRunner, session_factory: SessionFactory
) -> None:
    def handler(context: JobContext) -> dict[str, Any]:
        context.append_log("first")
        context.pause("hold on")
        context.resume()
        context.append_log("second")
        return {}

    runner.register(JOB_TYPE, handler)

    job = await runner.submit(JOB_TYPE, None, {})
    done = await wait_for(session_factory, job.id)

    assert done.log.splitlines() == ["first", "second"]


async def test_a_failing_handler_fails_its_job_and_the_runner_carries_on(
    runner: JobRunner, session_factory: SessionFactory
) -> None:
    async def handler(context: JobContext) -> dict[str, Any]:
        if context.params["explode"]:
            raise ValueError("the template is broken")
        return {"ok": True}

    runner.register(JOB_TYPE, handler)

    bad = await runner.submit(JOB_TYPE, None, {"explode": True})
    good = await runner.submit(JOB_TYPE, None, {"explode": False})
    failed = await wait_for(session_factory, bad.id)
    succeeded = await wait_for(session_factory, good.id)

    assert failed.status is JobStatus.FAILED
    assert failed.result == {"error": "the template is broken"}
    assert failed.log.endswith("the template is broken")
    assert succeeded.status is JobStatus.DONE


async def test_a_job_type_without_a_handler_fails(
    runner: JobRunner, session_factory: SessionFactory
) -> None:
    job = await runner.submit(JobType.REINGEST, None, {})

    failed = await wait_for(session_factory, job.id)

    assert failed.status is JobStatus.FAILED
    assert failed.result is not None
    assert "reingest" in failed.result["error"]


async def test_no_more_jobs_run_at_once_than_the_concurrency_bound(
    session_factory: SessionFactory, tmp_path: Path
) -> None:
    bounded = JobRunner(session_factory, tmp_path, max_concurrent=2)
    running = peak = 0
    gate = asyncio.Event()

    async def handler(_: JobContext) -> dict[str, Any]:
        nonlocal running, peak
        running += 1
        peak = max(peak, running)
        await gate.wait()
        running -= 1
        return {}

    bounded.register(JOB_TYPE, handler)
    await bounded.start()
    jobs = [await bounded.submit(JOB_TYPE, None, {}) for _ in range(5)]

    await asyncio.sleep(0.1)
    assert (running, peak) == (2, 2)
    gate.set()
    for job in jobs:
        assert (await wait_for(session_factory, job.id)).status is JobStatus.DONE
    await bounded.stop()

    assert peak == 2


async def test_jobs_left_unfinished_by_a_previous_process_are_interrupted_not_rerun(
    session_factory: SessionFactory, tmp_path: Path
) -> None:
    async with session_factory() as session:
        pending = await repository.create_job(session, JOB_TYPE, None)
        running = await repository.create_job(session, JOB_TYPE, None)
        await repository.mark_running(session, running.id)
        paused = await repository.create_job(session, JOB_TYPE, None)
        await repository.mark_paused(session, paused.id, "Do the thing")
    calls: list[JobContext] = []

    async def handler(context: JobContext) -> dict[str, Any]:
        calls.append(context)
        return {}

    fresh = JobRunner(session_factory, tmp_path)
    fresh.register(JOB_TYPE, handler)
    await fresh.start()
    await asyncio.sleep(0.05)
    await fresh.stop()

    for job_id in (pending.id, running.id, paused.id):
        assert (await stored(session_factory, job_id)).status is JobStatus.INTERRUPTED
    assert calls == []


async def test_stopping_interrupts_the_running_job_and_the_ones_still_waiting(
    session_factory: SessionFactory, tmp_path: Path
) -> None:
    single = JobRunner(session_factory, tmp_path, max_concurrent=1)
    started = asyncio.Event()

    async def handler(_: JobContext) -> dict[str, Any]:
        started.set()
        await asyncio.sleep(60)
        return {}

    single.register(JOB_TYPE, handler)
    await single.start()
    running = await single.submit(JOB_TYPE, None, {})
    waiting = await single.submit(JOB_TYPE, None, {})
    await asyncio.wait_for(started.wait(), TIMEOUT_S)

    await single.stop()

    for job in (running, waiting):
        assert (await stored(session_factory, job.id)).status is JobStatus.INTERRUPTED


async def test_subscribers_see_a_job_go_from_pending_to_done_in_order(
    runner: JobRunner, session_factory: SessionFactory
) -> None:
    async def handler(context: JobContext) -> dict[str, Any]:
        context.report_progress("Rendering", 30)
        context.report_progress("Writing", 80)
        return {"file": "a.pdf"}

    runner.register(JOB_TYPE, handler)
    with runner.feed.subscribe() as subscription:
        job = await runner.submit(JOB_TYPE, None, {})
        await wait_for(session_factory, job.id)
        seen = [subscription.inbox.get_nowait() for _ in range(subscription.inbox.qsize())]

    assert [(m.job.status, m.job.step, m.job.progress) for m in seen] == [
        (JobStatus.PENDING, "", 0),
        (JobStatus.RUNNING, "", 0),
        (JobStatus.RUNNING, "Rendering", 30),
        (JobStatus.RUNNING, "Writing", 80),
        (JobStatus.DONE, "Writing", 100),
    ]
    assert seen[-1].job.result == {"file": "a.pdf"}
    assert {m.job.id for m in seen} == {job.id}


async def test_a_new_subscriber_is_handed_the_jobs_still_active(
    runner: JobRunner, session_factory: SessionFactory
) -> None:
    release = asyncio.Event()

    async def handler(_: JobContext) -> dict[str, Any]:
        await release.wait()
        return {}

    runner.register(JOB_TYPE, handler)
    job = await runner.submit(JOB_TYPE, None, {})
    await wait_until(session_factory, job.id, lambda row: row.status is JobStatus.RUNNING)

    with runner.feed.subscribe() as subscription:
        snapshot: list[JobMessage] = subscription.snapshot
        release.set()
        await wait_for(session_factory, job.id)

    assert [(m.job.id, m.job.status) for m in snapshot] == [(job.id, JobStatus.RUNNING)]
    with runner.feed.subscribe() as later:
        assert later.snapshot == []


async def test_an_unsubscribed_inbox_receives_nothing_more(runner: JobRunner) -> None:
    with runner.feed.subscribe() as subscription:
        pass

    await runner.submit(JOB_TYPE, None, {})

    assert subscription.inbox.empty()
