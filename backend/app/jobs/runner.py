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


class ExpectedJobError(Exception):
    """A failure that is an outcome of the job, not a bug: the job ends FAILED with its message
    and the runner logs it without a traceback."""


def _ignore(*_: object) -> None:
    pass


@dataclass(frozen=True)
class JobContext:
    """What a handler is given. The reporting callables may be called from a handler's thread.

    `pause` and `resume` are for a job that waits for a person: the instructions travel in the
    job's `result` while it is `paused`.
    """

    job_id: int
    analysis_id: int | None
    params: Mapping[str, Any]
    exports_dir: Path
    report_progress: ProgressReporter
    append_log: Callable[[str], None] = _ignore
    pause: Callable[[str], None] = _ignore
    resume: Callable[[], None] = _ignore

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


@dataclass(frozen=True)
class _Progress:
    step: str
    percent: int


@dataclass(frozen=True)
class _LogText:
    text: str


@dataclass(frozen=True)
class _Pause:
    instructions: str


@dataclass(frozen=True)
class _Resume:
    pass


type _Update = _Progress | _LogText | _Pause | _Resume


class _UpdateRelay:
    """Carries a handler's reports, which may come from its thread, to the event loop, where
    one task persists them in the order they were made."""

    def __init__(
        self,
        loop: asyncio.AbstractEventLoop,
        persist: Callable[[_Update], Awaitable[None]],
    ) -> None:
        self._loop = loop
        self._persist = persist
        self._updates: asyncio.Queue[_Update | None] = asyncio.Queue()
        self._closed = False

    def report_progress(self, step: str, percent: int) -> None:
        self.send(_Progress(step, max(0, min(100, percent))))

    def send(self, update: _Update) -> None:
        if not self._closed:
            self._enqueue(update)

    def close(self) -> None:
        # Through the same scheduling as `send`, so the end marker cannot overtake an update.
        self._closed = True
        self._enqueue(None)

    def _enqueue(self, update: _Update | None) -> None:
        with contextlib.suppress(RuntimeError):  # the loop is gone: the process is shutting down
            self._loop.call_soon_threadsafe(self._updates.put_nowait, update)

    async def run(self) -> None:
        while (update := await self._updates.get()) is not None:
            try:
                await self._persist(update)
            except Exception:
                logger.exception("Persisting a job's report failed")


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
        relay = _UpdateRelay(
            asyncio.get_running_loop(), lambda update: self._persist_update(job_id, update)
        )
        relay_task = asyncio.create_task(relay.run())
        try:
            await self._persist(lambda db: repository.mark_running(db, job_id))
            result = await self._execute(submission, relay)
            relay.close()
            await relay_task
            await self._end(job_id, JobStatus.DONE, result)
        except asyncio.CancelledError:
            relay_task.cancel()
            await self._end(job_id, JobStatus.INTERRUPTED, {})
            raise
        except Exception as error:
            if isinstance(error, ExpectedJobError):
                logger.info("Job %s (%s) ended: %s", job_id, submission.job_type, error)
            else:
                logger.exception("Job %s (%s) failed", job_id, submission.job_type)
            relay.close()
            await relay_task
            reason = str(error) or type(error).__name__
            await self._end(job_id, JobStatus.FAILED, {"error": reason}, reason)

    async def _persist_update(self, job_id: int, update: _Update) -> None:
        match update:
            case _Progress(step, percent):
                await self._persist(
                    lambda db: repository.record_progress(db, job_id, step, percent)
                )
            case _LogText(text):
                await self._persist(lambda db: repository.record_log(db, job_id, text))
            case _Pause(instructions):
                await self._persist(lambda db: repository.mark_paused(db, job_id, instructions))
            case _Resume():
                await self._persist(lambda db: repository.mark_running(db, job_id))

    async def _execute(self, submission: _Submission, relay: _UpdateRelay) -> JobResult:
        handler = self._handlers.get(submission.job_type)
        if handler is None:
            raise LookupError(f"No handler is registered for {submission.job_type} jobs")
        context = JobContext(
            job_id=submission.job_id,
            analysis_id=submission.analysis_id,
            params=submission.params,
            exports_dir=self._exports_dir,
            report_progress=relay.report_progress,
            append_log=lambda text: relay.send(_LogText(text)),
            pause=lambda instructions: relay.send(_Pause(instructions)),
            resume=lambda: relay.send(_Resume()),
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
