import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import analysis_repository
from app.db import job_repository as repository
from app.db.models import Job
from app.db.models.job import LOG_TAIL_LIMIT, JobStatus, JobType
from tests.test_analysis_repository import seeded_analysis


async def test_a_new_job_is_pending_with_no_progress(session: AsyncSession) -> None:
    analysis = await seeded_analysis(session)

    job = await repository.create_job(session, JobType.EXPORT_REPORT, analysis.id)

    assert job.id is not None
    assert (job.type, job.analysis_id, job.status) == (
        JobType.EXPORT_REPORT,
        analysis.id,
        JobStatus.PENDING,
    )
    assert (job.step, job.progress, job.log, job.result) == ("", 0, "", None)
    assert job.created_at is not None


async def test_a_job_need_not_belong_to_an_analysis(session: AsyncSession) -> None:
    job = await repository.create_job(session, JobType.GUEST_BUILD, None)

    assert job.analysis_id is None


async def test_an_unknown_job_is_not_found(session: AsyncSession) -> None:
    assert await repository.get_job(session, 999) is None


async def test_a_job_runs_reports_progress_and_finishes(session: AsyncSession) -> None:
    job = await repository.create_job(session, JobType.INGEST, None)

    await repository.mark_running(session, job.id)
    running_status = job.status
    await repository.record_progress(session, job.id, "Reading the report", 40)
    reported = (job.step, job.progress)
    created_at = job.created_at
    done = await repository.finish_job(session, job.id, JobStatus.DONE, {"file": "a.pdf"})

    assert running_status is JobStatus.RUNNING
    assert reported == ("Reading the report", 40)
    assert done.status is JobStatus.DONE
    assert (done.progress, done.step, done.result) == (100, "Reading the report", {"file": "a.pdf"})
    assert done.updated_at > created_at


async def test_progress_is_persisted_for_another_session(
    session: AsyncSession, session_factory: object
) -> None:
    job = await repository.create_job(session, JobType.INGEST, None)
    await repository.record_progress(session, job.id, "Halfway", 50)

    async with session_factory() as other:  # type: ignore[operator]
        stored = await repository.get_job(other, job.id)

    assert stored is not None
    assert (stored.step, stored.progress) == ("Halfway", 50)


@pytest.mark.parametrize("status", [JobStatus.FAILED, JobStatus.INTERRUPTED])
async def test_a_job_that_did_not_finish_keeps_its_progress(
    session: AsyncSession, status: JobStatus
) -> None:
    job = await repository.create_job(session, JobType.INGEST, None)
    await repository.record_progress(session, job.id, "Halfway", 50)

    ended = await repository.finish_job(session, job.id, status, {"error": "boom"}, "it broke")

    assert (ended.status, ended.progress, ended.result) == (status, 50, {"error": "boom"})
    assert ended.log.endswith("it broke")


async def test_each_progress_report_adds_a_line_to_the_log(session: AsyncSession) -> None:
    job = await repository.create_job(session, JobType.INGEST, None)

    await repository.record_progress(session, job.id, "Reading", 10)
    stored = await repository.record_progress(session, job.id, "Writing", 90)

    assert stored.log.splitlines() == ["10% Reading", "90% Writing"]


async def test_the_log_keeps_only_its_tail(session: AsyncSession) -> None:
    job = await repository.create_job(session, JobType.INGEST, None)

    for number in range(LOG_TAIL_LIMIT):
        stored = await repository.record_progress(session, job.id, f"step {number}", 1)

    assert len(stored.log) <= LOG_TAIL_LIMIT
    assert stored.log.endswith(f"step {LOG_TAIL_LIMIT - 1}")
    assert "step 0\n" not in stored.log


def test_a_log_cut_to_its_tail_starts_on_a_whole_line() -> None:
    log = repository.append_to_log("alpha\nbravo", "charlie", limit=10)

    assert log == "charlie"
    assert repository.append_to_log("", "x" * 50, limit=10) == "x" * 10


async def test_unfinished_jobs_are_interrupted_and_finished_ones_left_alone(
    session: AsyncSession,
) -> None:
    pending = await repository.create_job(session, JobType.INGEST, None)
    running = await repository.create_job(session, JobType.INGEST, None)
    await repository.mark_running(session, running.id)
    done = await repository.create_job(session, JobType.INGEST, None)
    await repository.finish_job(session, done.id, JobStatus.DONE, {})

    interrupted = await repository.interrupt_unfinished(session)

    assert sorted(job.id for job in interrupted) == sorted([pending.id, running.id])
    statuses = {job.id: job.status for job in await session.scalars(select(Job))}
    assert statuses == {
        pending.id: JobStatus.INTERRUPTED,
        running.id: JobStatus.INTERRUPTED,
        done.id: JobStatus.DONE,
    }


async def test_an_active_job_is_found_by_its_analysis(session: AsyncSession) -> None:
    analysis = await seeded_analysis(session)
    other = await seeded_analysis(session, sha256="e" * 64)
    job = await repository.create_job(session, JobType.EXPORT_REPORT, analysis.id)

    assert await repository.has_active_job(session, analysis.id)
    assert not await repository.has_active_job(session, other.id)
    await repository.mark_running(session, job.id)
    assert await repository.has_active_job(session, analysis.id)
    await repository.finish_job(session, job.id, JobStatus.DONE, {})
    assert not await repository.has_active_job(session, analysis.id)


async def test_deleting_an_analysis_deletes_its_jobs(session: AsyncSession) -> None:
    analysis = await seeded_analysis(session)
    await repository.create_job(session, JobType.EXPORT_REPORT, analysis.id)
    unrelated = await repository.create_job(session, JobType.GUEST_BUILD, None)

    await analysis_repository.delete_analysis(session, analysis.id)

    assert [job.id for job in await session.scalars(select(Job))] == [unrelated.id]
