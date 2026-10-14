import asyncio
import contextlib
import inspect
import logging
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db import job_repository as repository
from app.db.models import Job
from app.db.models.job import JobStatus, JobType
from app.jobs.exports import analysis_exports_dir
from app.jobs.feed import JobFeed
from app.schemas.jobs import JobProgress
from app.ws.messages import JobMessage

logger = logging.getLogger(__name__)

MAX_CONCURRENT_JOBS = 2

type ProgressReporter = Callable[[str, int], None]
type JobResult = dict[str, Any]


@dataclass(frozen=True)
class JobContext:
    job_id: int
    analysis_id: int | None
    params: Mapping[str, Any]
    exports_dir: Path
    report_progress: ProgressReporter

    def analysis_dir(self) -> Path:
        """The analysis's own exports directory, created if needed."""
        if self.analysis_id is None:
            raise ValueError("This job has no analysis, so it has no exports directory of its own")
        directory = analysis_exports_dir(self.exports_dir, self.analysis_id)
        directory.mkdir(parents=True, exist_ok=True)
        return directory


type SyncJobHandler = Callable[[JobContext], JobResult]
type AsyncJobHandler = Callable[[JobContext], Awaitable[JobResult]]
type JobHandler = SyncJobHandler | AsyncJobHandler


@dataclass(frozen=True)
class _Submission:
    job_id: int
    analysis_id: int | None
    job_type: JobType
    params: Mapping[str, Any]


class _ProgressRelay:
    """Carries `report_progress` calls, which may come from a handler's thread, to the event
    loop, where one task persists them in the order they were made."""

    def __init__(
        self,
        loop: asyncio.AbstractEventLoop,
        persist: Callable[[str, int], Awaitable[None]],
    ) -> None:
        self._loop = loop
        self._persist = persist
        self._updates: asyncio.Queue[tuple[str, int] | None] = asyncio.Queue()
        self._closed = False

    def report(self, step: str, percent: int) -> None:
        if not self._closed:
            self._enqueue((step, max(0, min(100, percent))))

    def close(self) -> None:
        # Through the same scheduling as `report`, so the end marker cannot overtake an update.
        self._closed = True
        self._enqueue(None)

    def _enqueue(self, update: tuple[str, int] | None) -> None:
        with contextlib.suppress(RuntimeError):  # the loop is gone: the process is shutting down
            self._loop.call_soon_threadsafe(self._updates.put_nowait, update)

    async def run(self) -> None:
        while (update := await self._updates.get()) is not None:
            try:
                await self._persist(*update)
            except Exception:
                logger.exception("Persisting a job's progress failed")


class JobRunner:
    """Runs the registered handlers of persisted jobs, a bounded number at a time.

    A handler is a function (or coroutine function) taking a `JobContext` and returning the
    job's `result`. Sync handlers run in a thread. A job a previous process left unfinished is
    marked `interrupted` at `start()` and never run again.
    """

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        exports_dir: Path,
        *,
        max_concurrent: int = MAX_CONCURRENT_JOBS,
    ) -> None:
        self._session_factory = session_factory
        self._exports_dir = exports_dir
        self._max_concurrent = max_concurrent
        self._handlers: dict[JobType, JobHandler] = {}
        self._waiting: asyncio.Queue[_Submission] = asyncio.Queue()
        self._workers: list[asyncio.Task[None]] = []
        self.feed = JobFeed()

    def register(self, job_type: JobType, handler: JobHandler) -> None:
        self._handlers[job_type] = handler

    async def submit(
        self, job_type: JobType, analysis_id: int | None, params: Mapping[str, Any]
    ) -> Job:
        """Stores a pending job and queues it. `params` live in memory only: a job that
        outlives the process is interrupted, not resumed."""
        async with self._session_factory() as session:
            job = await repository.create_job(session, job_type, analysis_id)
        self._publish(job)
        self._waiting.put_nowait(_Submission(job.id, analysis_id, job_type, params))
        return job

    async def start(self) -> None:
        if self._workers:
            raise RuntimeError("The job runner is already started")
        await self._interrupt_left_over_jobs()
        self._workers = [
            asyncio.create_task(self._work(), name=f"job-worker-{number}")
            for number in range(self._max_concurrent)
        ]

    async def stop(self) -> None:
        """Cancels the running jobs and marks them, and the ones still waiting, interrupted.

        A sync handler's thread cannot be cancelled: it runs on, unobserved, until it returns.
        """
        for worker in self._workers:
            worker.cancel()
        await asyncio.gather(*self._workers, return_exceptions=True)
        self._workers = []
        while not self._waiting.empty():
            await self._end(self._waiting.get_nowait().job_id, JobStatus.INTERRUPTED, {})

    async def _interrupt_left_over_jobs(self) -> None:
        try:
            async with self._session_factory() as session:
                interrupted = await repository.interrupt_unfinished(session)
        except Exception:
            logger.exception("Marking the jobs a previous process left unfinished failed")
            return
        for job in interrupted:
            self._publish(job)

    async def _work(self) -> None:
        while True:
            submission = await self._waiting.get()
            try:
                await self._run(submission)
            except Exception:
                logger.exception("Running job %s failed unexpectedly", submission.job_id)

    async def _run(self, submission: _Submission) -> None:
        job_id = submission.job_id
        relay = _ProgressRelay(
            asyncio.get_running_loop(),
            lambda step, percent: self._persist(
                lambda db: repository.record_progress(db, job_id, step, percent)
            ),
        )
        relay_task = asyncio.create_task(relay.run())
        try:
            await self._persist(lambda db: repository.mark_running(db, job_id))
            result = await self._execute(submission, relay.report)
            relay.close()
            await relay_task
            await self._end(job_id, JobStatus.DONE, result)
        except asyncio.CancelledError:
            relay_task.cancel()
            await self._end(job_id, JobStatus.INTERRUPTED, {})
            raise
        except Exception as error:
            logger.exception("Job %s (%s) failed", job_id, submission.job_type)
            relay.close()
            await relay_task
            reason = str(error) or type(error).__name__
            await self._end(job_id, JobStatus.FAILED, {"error": reason}, reason)

    async def _execute(
        self, submission: _Submission, report_progress: ProgressReporter
    ) -> JobResult:
        handler = self._handlers.get(submission.job_type)
        if handler is None:
            raise LookupError(f"No handler is registered for {submission.job_type} jobs")
        context = JobContext(
            job_id=submission.job_id,
            analysis_id=submission.analysis_id,
            params=submission.params,
            exports_dir=self._exports_dir,
            report_progress=report_progress,
        )
        if inspect.iscoroutinefunction(handler):
            return await cast(AsyncJobHandler, handler)(context)
        return await asyncio.to_thread(cast(SyncJobHandler, handler), context)

    async def _end(
        self, job_id: int, status: JobStatus, result: JobResult, log_line: str | None = None
    ) -> None:
        try:
            await self._persist(
                lambda db: repository.finish_job(db, job_id, status, result, log_line)
            )
        except Exception:
            logger.exception("Recording that job %s ended as %s failed", job_id, status)

    async def _persist(self, write: Callable[[AsyncSession], Awaitable[Job]]) -> None:
        async with self._session_factory() as session:
            job = await write(session)
        self._publish(job)

    def _publish(self, job: Job) -> None:
        self.feed.publish(JobMessage(job=JobProgress.model_validate(job)))
