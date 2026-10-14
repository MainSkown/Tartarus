from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Job
from app.db.models.job import ACTIVE_JOB_STATUSES, LOG_TAIL_LIMIT, JobStatus, JobType


async def create_job(session: AsyncSession, job_type: JobType, analysis_id: int | None) -> Job:
    job = Job(type=job_type, analysis_id=analysis_id)
    session.add(job)
    await session.commit()
    return job


async def get_job(session: AsyncSession, job_id: int) -> Job | None:
    return await session.get(Job, job_id)


async def mark_running(session: AsyncSession, job_id: int) -> Job:
    job = await _require(session, job_id)
    job.status = JobStatus.RUNNING
    await session.commit()
    return job


async def record_progress(session: AsyncSession, job_id: int, step: str, progress: int) -> Job:
    job = await _require(session, job_id)
    job.step = step
    job.progress = progress
    job.log = append_to_log(job.log, f"{progress}% {step}")
    await session.commit()
    return job


async def finish_job(
    session: AsyncSession,
    job_id: int,
    status: JobStatus,
    result: dict[str, Any],
    log_line: str | None = None,
) -> Job:
    """Ends the job; only a `done` one is complete, so only it jumps to 100%."""
    job = await _require(session, job_id)
    job.status = status
    job.result = result
    if status is JobStatus.DONE:
        job.progress = 100
    if log_line is not None:
        job.log = append_to_log(job.log, log_line)
    await session.commit()
    return job


async def interrupt_unfinished(session: AsyncSession) -> list[Job]:
    """For jobs a dead process left behind: they are not run again, only marked."""
    jobs = list(await session.scalars(select(Job).where(Job.status.in_(ACTIVE_JOB_STATUSES))))
    for job in jobs:
        job.status = JobStatus.INTERRUPTED
    await session.commit()
    return jobs


async def has_active_job(session: AsyncSession, analysis_id: int) -> bool:
    found = await session.scalar(
        select(Job.id)
        .where(Job.analysis_id == analysis_id, Job.status.in_(ACTIVE_JOB_STATUSES))
        .limit(1)
    )
    return found is not None


def append_to_log(log: str, line: str, limit: int = LOG_TAIL_LIMIT) -> str:
    """Adds a line and keeps the last `limit` characters, cut at a line start where it can."""
    grown = f"{log}\n{line}" if log else line
    if len(grown) <= limit:
        return grown
    tail = grown[-limit:]
    _, newline, after_first_line = tail.partition("\n")
    return after_first_line if newline else tail


async def _require(session: AsyncSession, job_id: int) -> Job:
    job = await session.get(Job, job_id)
    if job is None:
        raise LookupError(f"Job {job_id} does not exist")
    return job
