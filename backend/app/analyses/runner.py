import asyncio
import contextlib
import logging
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from http import HTTPStatus
from pathlib import Path
from typing import Any, Protocol, Self, Unpack

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.analyses.deadline import MAX_RUN_S, initial_deadline
from app.analyses.defender import DefenderVerdict
from app.analyses.guest_choice import recorded_guest
from app.analyses.memory import MemorySummary
from app.analyses.memory_step import MemoryStep
from app.analyses.monitor import first_monitor_log_time
from app.analyses.pcap_import import ImportRefusedError, Submitted, submit_import
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
from app.db.models.analysis import ACTIVE_STATUSES, AnalysisKind, AnalysisPhase, AnalysisStatus
from app.guest.errors import (
    GuestControlError,
    GuestControlNotConfigured,
    GuestControlRejected,
    GuestControlUnreachable,
)
from app.guest.schemas import Guest, InteractiveOptions
from app.live.utc import as_utc

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

    async def create_pcap_task(self, source: Path, filename: str) -> int: ...

    async def task_status(self, task_id: int) -> str: ...

    async def task_view(self, task_id: int) -> TaskView: ...


@dataclass(frozen=True)
class RunnerConfig:
    cape_storage_path: Path
    poll_interval: float
    unreachable_grace: float
    shutdown_patience: float = 10.0
    live_stop_timeout: float = 10.0
    imports_dir: Path = Path("/imports")

    @classmethod
    def from_settings(cls, settings: Settings) -> Self:
        return cls(
            cape_storage_path=settings.cape_storage_path,
            poll_interval=settings.runner_poll_interval_seconds,
            unreachable_grace=settings.runner_unreachable_grace_seconds,
            imports_dir=settings.imports_dir,
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
        now: Callable[[], datetime] = utc_now,
        live: LiveCollection | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._cape = cape
        self._samples = samples
        self._read_report = read_report
        self._ingester = ingester
        self._guests = guests
        self._memory = MemoryStep(guests, config.cape_storage_path)
        self._config = config
        self._clock = clock
        self._now = now
        self._live = live or NoLiveCollection()
        self._collecting: int | None = None
        self._trouble_since: dict[int, float] = {}
        self._consecutive_errors: dict[int, int] = {}
        self._end_requested: set[int] = set()
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
        """One pass over each queue; never raises, so a bad tick cannot stop the loop.

        An import needs no guest, so its queue is followed apart from the runs': neither waits
        for the other's analysis to end.
        """
        for kind in (AnalysisKind.RUN, AnalysisKind.IMPORTED):
            await self._tick(kind)

    async def _tick(self, kind: AnalysisKind) -> None:
        try:
            async with self._session_factory() as session:
                active = await get_active_analysis(session, kind)
                if active is None:
                    await self._start_next(session, kind)
                else:
                    await self._track_guarded(session, active)
        except Exception:
            logger.exception("Runner tick failed")

    async def _start_next(self, session: AsyncSession, kind: AnalysisKind) -> None:
        while (queued := await get_oldest_queued_analysis(session, kind)) is not None:
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
            submitted = await self._upload(claimed)
        except (CapeUnreachable, GuestControlUnreachable) as unreachable:
            if isinstance(unreachable, GuestControlNotConfigured):
                await self._finish(
                    session, claimed.id, status=AnalysisStatus.FAILED, error=str(unreachable)
                )
                return
            logger.warning("Analysis %s goes back to the queue: %s", claimed.id, unreachable)
            await update_analysis(session, claimed.id, status=AnalysisStatus.QUEUED)
        except (GuestUnavailableError, GuestControlError, ImportRefusedError) as unavailable:
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
            await update_analysis(
                session, claimed.id, cape_task_id=submitted.task_id, started_at=submitted.started_at
            )

    async def _upload(self, analysis: Analysis) -> Submitted:
        if analysis.kind is AnalysisKind.IMPORTED:
            return await submit_import(self._cape, analysis, self._config.imports_dir)
        options = analysis.options
        guest = await self._guest_of(analysis)
        is_interactive = options.get("interactive") is True
        interactive = await self._interactive_options(guest) if is_interactive else NOT_INTERACTIVE
        async with self._samples.open_plain(analysis.sample_sha256) as path:
            task_id = await self._cape.create_file_task(
                path,
                analysis.filename,
                machine=guest.name,
                route=options["route"],
                # The backend ends interactive runs at their deadline; CAPE only backstops them.
                timeout=MAX_RUN_S if is_interactive else options["timeout"],
                package=options.get("package", "auto"),
                options=interactive.options,
                task_fields=_task_fields(options, interactive),
            )
        return Submitted(task_id)

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
                self._trouble_since.pop(analysis.id, None)
                await self._steer_interactive_run(session, analysis, task_id)
            else:
                await self._tolerate(session, analysis.id, trouble)

    async def _steer_interactive_run(
        self, session: AsyncSession, analysis: Analysis, task_id: int
    ) -> None:
        started_at = analysis.started_at
        if not _is_interactive_run(analysis) or started_at is None:
            return
        if analysis.status is not AnalysisStatus.RUNNING:
            self._end_requested.discard(analysis.id)
            return
        if analysis.deadline_at is None:
            await self._set_deadline(session, analysis, task_id, started_at)
        if self._deadline_passed(analysis):
            await self._end_run(analysis, task_id)

    async def _set_deadline(
        self, session: AsyncSession, analysis: Analysis, task_id: int, started_at: datetime
    ) -> None:
        monitor_seen_at = first_monitor_log_time(self._config.cape_storage_path, task_id)
        if monitor_seen_at is None:
            return
        deadline = initial_deadline(
            as_utc(monitor_seen_at), as_utc(started_at), analysis.options["timeout"]
        )
        await update_analysis(session, analysis.id, deadline_at=deadline)

    def _deadline_passed(self, analysis: Analysis) -> bool:
        return analysis.deadline_at is not None and self._now() >= as_utc(analysis.deadline_at)

    async def _end_run(self, analysis: Analysis, task_id: int) -> None:
        # Once the guest accepted the end it shuts down, so a repeat would only hit a dead agent.
        if analysis.id in self._end_requested:
            return
        guest = recorded_guest(analysis.options)
        if guest is None:
            return
        try:
            await self._guests.finish_task(task_id, guest)
        except GuestControlError as error:
            logger.warning(
                "Ending analysis %s at its deadline failed, retrying: %s", analysis.id, error
            )
        else:
            self._end_requested.add(analysis.id)

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
        trouble_since = self._trouble_since.setdefault(analysis_id, now)
        seconds = round(now - trouble_since)
        logger.warning(
            "CAPE has been %s for %s seconds (analysis %s)", trouble, seconds, analysis_id
        )
        if now - trouble_since > self._config.unreachable_grace:
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
            await self._ingest(session, analysis, task_id)

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

    async def _ingest(self, session: AsyncSession, analysis: Analysis, task_id: int) -> None:
        analysis_id = analysis.id
        report_file = self._config.cape_storage_path / "analyses" / str(task_id) / "reports"
        report_file /= "report.json"
        try:
            outcome = await asyncio.to_thread(self._read_report, report_file)
        except ReportUnreadableError as unreadable:
            await self._finish(
                session, analysis_id, status=AnalysisStatus.REPORT_FAILED, error=str(unreadable)
            )
            return
        memory = await self._memory.run(analysis, task_id)
        try:
            indexed = await self._ingester.ingest(
                analysis_id, report_file, started_at=_capture_start(analysis)
            )
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
        memory = await self._memory.release(analysis, task_id, memory)
        await self._finish_done(session, analysis_id, outcome, indexed, memory)

    async def _finish_done(
        self,
        session: AsyncSession,
        analysis_id: int,
        outcome: ReportOutcome,
        indexed: IngestResult,
        memory: MemorySummary | None,
    ) -> None:
        await self._finish(
            session,
            analysis_id,
            status=AnalysisStatus.DONE,
            phase=AnalysisPhase.FINAL,
            score=outcome.score,
            max_severity=outcome.max_severity,
            detected_families=outcome.detected_families,
            summary={
                **outcome.summary,
                "lane_counts": indexed.lane_counts,
                "defender": _dumped(indexed.defender),
                "hidden_events": indexed.hidden_events,
                **({} if memory is None else {"memory": memory.model_dump(mode="json")}),
            },
            event_count=indexed.event_count,
        )

    def _start_live_if_running(self, analysis: Analysis, task_id: int) -> None:
        if (
            analysis.kind is not AnalysisKind.RUN
            or analysis.status is not AnalysisStatus.RUNNING
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
        self._trouble_since.pop(analysis_id, None)
        self._consecutive_errors.pop(analysis_id, None)
        self._end_requested.discard(analysis_id)
        logger.info("Analysis %s ended as %s", analysis_id, changes["status"])


def _dumped(verdict: DefenderVerdict | None) -> dict[str, Any] | None:
    return None if verdict is None else verdict.model_dump(mode="json")


def _task_fields(
    options: Mapping[str, Any], interactive: InteractiveOptions
) -> dict[str, bool | int | str]:
    # CAPE reads `memory` as a form field; as an entry of the `options` string it takes no dump.
    asked_for_dump = options.get("memory_dump") is True
    return {**interactive.task_fields, **({"memory": True} if asked_for_dump else {})}


def _capture_start(analysis: Analysis) -> datetime | None:
    if analysis.kind is not AnalysisKind.IMPORTED or analysis.started_at is None:
        return None
    return as_utc(analysis.started_at)


def _is_interactive_run(analysis: Analysis) -> bool:
    return analysis.options.get("interactive") is True


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
