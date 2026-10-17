import asyncio
import contextlib
import logging
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from http import HTTPStatus
from pathlib import Path
from typing import Protocol, Self, Unpack

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.analyses.deadline import MAX_RUN_S
from app.analyses.guest_choice import recorded_guest
from app.analyses.ports import (
    EventIngester,
    GuestSource,
    IngestFailedError,
    IngestResult,
    LiveCollection,
    NoLiveCollection,
    ReportOutcome,
    ReportReader,
    ReportUnreadableError,
    SampleSource,
)
from app.cape.errors import (
    CapeAuthError,
    CapeError,
    CapeNotConfigured,
    CapeRejected,
    CapeTaskNotFound,
    CapeUnreachable,
)
from app.cape.models import TaskView
from app.cape.status import CapeProgress, progress_for
from app.config import Settings
from app.db.analysis_repository import (
    AnalysisChanges,
    claim_queued,
    get_active_analysis,
    get_oldest_queued_analysis,
    update_analysis,
)
from app.db.base import utc_now
from app.db.models import Analysis
from app.db.models.analysis import ACTIVE_STATUSES, AnalysisPhase, AnalysisStatus
from app.guest.errors import (
    GuestControlError,
    GuestControlNotConfigured,
    GuestControlRejected,
    GuestControlUnreachable,
)
from app.guest.schemas import Guest, InteractiveOptions

logger = logging.getLogger(__name__)

MAX_CONSECUTIVE_ERRORS = 3
NOT_INTERACTIVE = InteractiveOptions(options="")


class CapeTaskApi(Protocol):
    """The part of `CapeClient` the runner uses."""

    async def create_file_task(  # noqa: PLR0913 - mirrors CapeClient.create_file_task
        self,
        source: Path,
        filename: str,
        *,
        machine: str,
        route: str,
        timeout: int,  # noqa: ASYNC109 - CAPE's analysis timeout, not an asyncio one
        package: str = "auto",
        options: str = "",
        task_fields: Mapping[str, bool | int | str] | None = None,
    ) -> int: ...

    async def task_status(self, task_id: int) -> str: ...

    async def task_view(self, task_id: int) -> TaskView: ...


@dataclass(frozen=True)
class RunnerConfig:
    cape_storage_path: Path
    poll_interval: float
    unreachable_grace: float
    shutdown_patience: float = 10.0
    live_stop_timeout: float = 10.0

    @classmethod
    def from_settings(cls, settings: Settings) -> Self:
        return cls(
            cape_storage_path=settings.cape_storage_path,
            poll_interval=settings.runner_poll_interval_seconds,
            unreachable_grace=settings.runner_unreachable_grace_seconds,
        )


class GuestUnavailableError(Exception):
    """The analysis cannot be sent to CAPE because of its guest; the message says why."""


class Runner:
    """Feeds queued analyses to CAPE one at a time and follows the active one to its end.

    All state lives in the database, so a new runner carries on where a dead one stopped.
    """

    def __init__(  # noqa: PLR0913, PLR0917 - the runner's ports, injected so tests can fake each one
        self,
        session_factory: async_sessionmaker[AsyncSession],
        cape: CapeTaskApi,
        samples: SampleSource,
        read_report: ReportReader,
        ingester: EventIngester,
        guests: GuestSource,
        config: RunnerConfig,
        *,
        clock: Callable[[], float] = time.monotonic,
        live: LiveCollection | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._cape = cape
        self._samples = samples
        self._read_report = read_report
        self._ingester = ingester
        self._guests = guests
        self._config = config
        self._clock = clock
        self._live = live or NoLiveCollection()
        self._collecting: int | None = None
        self._trouble_since: float | None = None
        self._consecutive_errors: dict[int, int] = {}
        self._nudged = asyncio.Event()
        self._loop_task: asyncio.Task[None] | None = None
        self._stopping = False

    def start(self) -> None:
        if self._loop_task is not None:
            raise RuntimeError("The runner is already started")
        self._stopping = False
        self._loop_task = asyncio.create_task(self._loop(), name="analysis-runner")

    async def stop(self) -> None:
        """Lets the tick in progress finish, so a submission keeps its task id."""
        if self._loop_task is None:
            return
        self._stopping = True
        self.nudge()
        try:
            await asyncio.wait_for(asyncio.shield(self._loop_task), self._config.shutdown_patience)
        except TimeoutError:
            logger.warning("The runner's tick did not finish in time; cancelling it")
            self._loop_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._loop_task
        self._loop_task = None

    def nudge(self) -> None:
        """Check for work now instead of at the next poll. Never blocks and never raises."""
        self._nudged.set()

    async def _loop(self) -> None:
        while not self._stopping:
            # Cleared before the tick, so a nudge that arrives during it is not lost.
            self._nudged.clear()
            await self.run_once()
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._nudged.wait(), self._config.poll_interval)

    async def run_once(self) -> None:
        """One pass over the queue; never raises, so a bad tick cannot stop the loop."""
        try:
            async with self._session_factory() as session:
                active = await get_active_analysis(session)
                if active is None:
                    await self._start_next(session)
                else:
                    await self._track_guarded(session, active)
        except Exception:
            logger.exception("Runner tick failed")

    async def _start_next(self, session: AsyncSession) -> None:
        while (queued := await get_oldest_queued_analysis(session)) is not None:
            if await claim_queued(session, queued.id):
                # The claim is a bulk UPDATE the session did not see; without a refresh the
                # object still says `queued` and a later write of `queued` would be skipped.
                await session.refresh(queued)
                await self._submit_guarded(session, queued)
                return

    async def _submit_guarded(self, session: AsyncSession, claimed: Analysis) -> None:
        try:
            await self._submit(session, claimed)
        except Exception as error:
            logger.exception("Submitting analysis %s failed", claimed.id)
            async with self._session_factory() as fresh:
                await self._finish(
                    fresh,
                    claimed.id,
                    status=AnalysisStatus.FAILED,
                    error=f"Submitting to CAPE failed unexpectedly ({type(error).__name__})",
                )

    async def _submit(self, session: AsyncSession, claimed: Analysis) -> None:
        try:
            task_id = await self._upload(claimed)
        except (CapeUnreachable, GuestControlUnreachable) as unreachable:
            if isinstance(unreachable, GuestControlNotConfigured):
                await self._finish(
                    session, claimed.id, status=AnalysisStatus.FAILED, error=str(unreachable)
                )
                return
            logger.warning("Analysis %s goes back to the queue: %s", claimed.id, unreachable)
            await update_analysis(session, claimed.id, status=AnalysisStatus.QUEUED)
        except (GuestUnavailableError, GuestControlError) as unavailable:
            await self._finish(
                session, claimed.id, status=AnalysisStatus.FAILED, error=str(unavailable)
            )
        except FileNotFoundError:
            await self._finish(
                session,
                claimed.id,
                status=AnalysisStatus.FAILED,
                error="The stored sample file is missing, so it cannot be sent to CAPE",
            )
        except CapeRejected as rejected:
            await self._finish(
                session,
                claimed.id,
                status=AnalysisStatus.FAILED,
                error=f"CAPE refused the task: {rejected.message}",
            )
        except CapeError as error:
            # Auth, configuration or an unreadable answer: CAPE may or may not hold a task, so
            # resubmitting could duplicate it.
            await self._finish(session, claimed.id, status=AnalysisStatus.FAILED, error=str(error))
        else:
            await update_analysis(session, claimed.id, cape_task_id=task_id)

    async def _upload(self, analysis: Analysis) -> int:
        options = analysis.options
        guest = await self._guest_of(analysis)
        is_interactive = options.get("interactive") is True
        interactive = await self._interactive_options(guest) if is_interactive else NOT_INTERACTIVE
        async with self._samples.open_plain(analysis.sample_sha256) as path:
            return await self._cape.create_file_task(
                path,
                analysis.filename,
                machine=guest.name,
                route=options["route"],
                # The backend ends interactive runs at their deadline; CAPE only backstops them.
                timeout=MAX_RUN_S if is_interactive else options["timeout"],
                package=options.get("package", "auto"),
                options=interactive.options,
                task_fields=interactive.task_fields,
            )

    async def _guest_of(self, analysis: Analysis) -> Guest:
        name = recorded_guest(analysis.options)
        if name is None:
            raise GuestUnavailableError(
                "The analysis records no guest, so CAPE cannot be told which machine to use"
            )
        try:
            return await self._guests.guest(name)
        except GuestControlRejected as refused:
            if refused.status == HTTPStatus.NOT_FOUND:
                raise GuestUnavailableError(f"Guest {name} no longer exists") from None
            raise

    async def _interactive_options(self, guest: Guest) -> InteractiveOptions:
        profiles = await self._guests.profiles()
        profile = next((profile for profile in profiles if profile.id == guest.profile), None)
        if profile is None:
            raise GuestUnavailableError(
                f"The profile {guest.profile} of guest {guest.name} is not known, "
                "so its interactive options cannot be read"
            )
        return profile.agent.interactive

    async def _track_guarded(self, session: AsyncSession, analysis: Analysis) -> None:
        try:
            await self._track(session, analysis)
        except Exception as error:
            logger.exception("Tracking analysis %s failed", analysis.id)
            await self._count_unexpected_error(analysis.id, error)
        else:
            self._consecutive_errors.pop(analysis.id, None)

    async def _count_unexpected_error(self, analysis_id: int, error: Exception) -> None:
        count = self._consecutive_errors.get(analysis_id, 0) + 1
        self._consecutive_errors[analysis_id] = count
        if count < MAX_CONSECUTIVE_ERRORS:
            return
        # A fresh session: the one that raised may be unusable.
        async with self._session_factory() as session:
            await self._finish(
                session,
                analysis_id,
                status=AnalysisStatus.FAILED,
                error=f"Following the analysis failed {count} times ({type(error).__name__})",
            )

    async def _track(self, session: AsyncSession, analysis: Analysis) -> None:
        task_id = analysis.cape_task_id
        if task_id is None:
            await self._finish(
                session,
                analysis.id,
                status=AnalysisStatus.FAILED,
                error=(
                    "The analysis has no CAPE task id, so it cannot be followed "
                    "(the backend stopped while submitting it); submit the sample again"
                ),
            )
            return
        try:
            trouble = await self._follow(session, analysis, task_id)
        except CapeTaskNotFound:
            await self._finish_for_forgotten_task(session, analysis, task_id)
        except (CapeAuthError, CapeNotConfigured) as refused:
            await self._finish(
                session, analysis.id, status=AnalysisStatus.FAILED, error=str(refused)
            )
        except CapeError as error:
            await self._tolerate(session, analysis.id, _trouble_of(error))
        else:
            if trouble is None:
                self._trouble_since = None
            else:
                await self._tolerate(session, analysis.id, trouble)

    async def _finish_for_forgotten_task(
        self, session: AsyncSession, analysis: Analysis, task_id: int
    ) -> None:
        if analysis.status is AnalysisStatus.INGESTING:
            await self._finish(
                session,
                analysis.id,
                status=AnalysisStatus.REPORT_FAILED,
                error=f"CAPE no longer knows task {task_id}, so its report cannot be read again",
            )
            return
        await self._finish(
            session,
            analysis.id,
            status=AnalysisStatus.FAILED,
            error=f"CAPE no longer knows task {task_id}",
        )

    async def _tolerate(self, session: AsyncSession, analysis_id: int, trouble: str) -> None:
        """Waits out a CAPE problem, but only for the grace period."""
        now = self._clock()
        if self._trouble_since is None:
            self._trouble_since = now
        seconds = round(now - self._trouble_since)
        logger.warning(
            "CAPE has been %s for %s seconds (analysis %s)", trouble, seconds, analysis_id
        )
        if now - self._trouble_since > self._config.unreachable_grace:
            await self._finish(
                session,
                analysis_id,
                status=AnalysisStatus.FAILED,
                error=f"CAPE has been {trouble} for {seconds} seconds",
            )

    async def _follow(self, session: AsyncSession, analysis: Analysis, task_id: int) -> str | None:
        """Follows CAPE's task; returns what is wrong with CAPE, if anything."""
        raw_status = await self._cape.task_status(task_id)
        progress = progress_for(raw_status)
        if progress is CapeProgress.UNKNOWN:
            return f"reporting the unknown status {raw_status!r}"
        await self._apply(session, analysis, task_id, raw_status, progress)
        return None

    async def _apply(
        self,
        session: AsyncSession,
        analysis: Analysis,
        task_id: int,
        raw_status: str,
        progress: CapeProgress,
    ) -> None:
        if progress in (CapeProgress.FAILED, CapeProgress.REPORT_FAILED):
            await self._finish(
                session,
                analysis.id,
                status=AnalysisStatus(progress.value),
                error=f"CAPE ended the task as {raw_status}",
            )
            return
        await self._advance(session, analysis, task_id, AnalysisStatus(progress.value))
        self._start_live_if_running(analysis, task_id)
        if progress is CapeProgress.INGESTING:
            await self._ingest(session, analysis.id, task_id)

    async def _advance(
        self, session: AsyncSession, analysis: Analysis, task_id: int, target: AnalysisStatus
    ) -> None:
        if _stage(target) <= _stage(analysis.status):
            return
        if _stage(target) > _stage(AnalysisStatus.RUNNING):
            await self._stop_live(analysis.id)
        changes: AnalysisChanges = {"status": target}
        if analysis.started_at is None and _stage(target) >= _stage(AnalysisStatus.RUNNING):
            view = await self._cape.task_view(task_id)
            changes["started_at"] = view.started_on or utc_now()
        await update_analysis(session, analysis.id, **changes)

    async def _ingest(self, session: AsyncSession, analysis_id: int, task_id: int) -> None:
        report_file = self._config.cape_storage_path / "analyses" / str(task_id) / "reports"
        report_file /= "report.json"
        try:
            outcome = await asyncio.to_thread(self._read_report, report_file)
        except ReportUnreadableError as unreadable:
            await self._finish(
                session, analysis_id, status=AnalysisStatus.REPORT_FAILED, error=str(unreadable)
            )
            return
        try:
            indexed = await self._ingester.ingest(analysis_id, report_file)
        except IngestFailedError as failure:
            # The ingester removes a half-built index, so no events are left to count.
            await self._finish(
                session,
                analysis_id,
                status=AnalysisStatus.REPORT_FAILED,
                error=str(failure),
                event_count=0,
            )
            return
        await self._finish_done(session, analysis_id, outcome, indexed)

    async def _finish_done(
        self, session: AsyncSession, analysis_id: int, outcome: ReportOutcome, indexed: IngestResult
    ) -> None:
        await self._finish(
            session,
            analysis_id,
            status=AnalysisStatus.DONE,
            phase=AnalysisPhase.FINAL,
            score=outcome.score,
            max_severity=outcome.max_severity,
            detected_families=outcome.detected_families,
            summary={**outcome.summary, "lane_counts": indexed.lane_counts},
            event_count=indexed.event_count,
        )

    def _start_live_if_running(self, analysis: Analysis, task_id: int) -> None:
        if (
            analysis.status is not AnalysisStatus.RUNNING
            or analysis.started_at is None
            or self._collecting == analysis.id
        ):
            return
        try:
            self._live.start(analysis.id, task_id, analysis.started_at)
        except Exception:
            logger.exception("Starting the live collection of analysis %s failed", analysis.id)
        else:
            self._collecting = analysis.id

    async def _stop_live(self, analysis_id: int) -> None:
        """Drains and ends the collection before the status moves on, so the final ingest never
        races the collector; a collector that fails or hangs is abandoned, never fatal."""
        if self._collecting != analysis_id:
            return
        self._collecting = None
        try:
            await asyncio.wait_for(self._live.stop(analysis_id), self._config.live_stop_timeout)
        except Exception:
            logger.exception("Stopping the live collection of analysis %s failed", analysis_id)

    async def _finish(
        self, session: AsyncSession, analysis_id: int, **changes: Unpack[AnalysisChanges]
    ) -> None:
        await self._stop_live(analysis_id)
        ended: AnalysisChanges = {**changes, "finished_at": utc_now()}
        await update_analysis(session, analysis_id, **ended)
        self._trouble_since = None
        self._consecutive_errors.pop(analysis_id, None)
        logger.info("Analysis %s ended as %s", analysis_id, changes["status"])


def _stage(status: AnalysisStatus) -> int:
    return ACTIVE_STATUSES.index(status)


def _trouble_of(error: CapeError) -> str:
    return "unreachable" if isinstance(error, CapeUnreachable) else f"failing ({error})"


def build_runner(  # noqa: PLR0913, PLR0917 - the runner's ports plus the settings
    session_factory: async_sessionmaker[AsyncSession],
    cape: CapeTaskApi,
    samples: SampleSource,
    read_report: ReportReader,
    ingester: EventIngester,
    guests: GuestSource,
    settings: Settings,
    live: LiveCollection | None = None,
) -> Runner:
    return Runner(
        session_factory,
        cape,
        samples,
        read_report,
        ingester,
        guests,
        RunnerConfig.from_settings(settings),
        live=live,
    )
