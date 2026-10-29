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
from app.analyses.memory_import import MemoryImport, MemoryImportFailedError, is_memory_image_import
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
from app.analyses.summary import SEVERITY_ORDER, ReportSummary
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
    get_active_analyses,
    get_analysis,
    get_oldest_startable_analysis,
    update_analysis,
)
from app.db.base import utc_now
from app.db.models import Analysis
from app.db.models.analysis import (
    ACTIVE_STATUSES,
    AnalysisKind,
    AnalysisPhase,
    AnalysisStatus,
    Severity,
)
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
# A memory image has no CAPE report, so nothing scores it or names a family.
IMAGE_OUTCOME = ReportOutcome(
    score=None,
    max_severity=None,
    detected_families=[],
    summary=ReportSummary().model_dump(mode="json"),
)
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
    """Feeds queued analyses to CAPE, one per guest at a time, and follows every active one to
    its end, each in its own task.

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
        self._images = MemoryImport(guests, ingester, config.cape_storage_path, config.imports_dir)
        self._memory_imports: dict[int, asyncio.Task[None]] = {}
        self._config = config
        self._clock = clock
        self._now = now
        self._live = live or NoLiveCollection()
        self._collecting: set[int] = set()
        self._followers: dict[int, asyncio.Task[None]] = {}
        self._follow_again: set[int] = set()
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
        """Lets the tick and the passes in progress finish, so a submission keeps its task id. A
        memory image being scanned is dropped; the next runner scans it again.
        """
        await self._stop_loop()
        await self._settle_followers()
        await self._cancel_memory_imports()

    async def wait_for_memory_imports(self) -> None:
        await asyncio.gather(*self._memory_imports.values())

    async def _stop_loop(self) -> None:
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

    async def _settle_followers(self) -> None:
        followers = list(self._followers.values())
        if not followers:
            return
        _, unfinished = await asyncio.wait(followers, timeout=self._config.shutdown_patience)
        if unfinished:
            logger.warning(
                "%s analyses were still being followed; cancelling them", len(unfinished)
            )
        for follower in unfinished:
            follower.cancel()
        await asyncio.gather(*unfinished, return_exceptions=True)

    async def _cancel_memory_imports(self) -> None:
        scans = list(self._memory_imports.values())
        for scan in scans:
            scan.cancel()
        await asyncio.gather(*scans, return_exceptions=True)

    def nudge(self) -> None:
        """Check for work now instead of at the next poll. Never blocks and never raises."""
        self._nudged.set()

    async def _loop(self) -> None:
        while not self._stopping:
            # Cleared before the tick, so a nudge that arrives during it is not lost.
            self._nudged.clear()
            await self._pass()
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._nudged.wait(), self._config.poll_interval)

    async def run_once(self) -> None:
        """One pass over each queue, then waits for the passes over the analyses it started.

        Never raises, so a bad tick cannot stop the loop. An analysis whose previous pass is
        still in progress (a slow ingest) is not waited for.
        """
        await asyncio.gather(*await self._pass())

    async def _pass(self) -> list[asyncio.Task[None]]:
        """Follows every active analysis in its own task and starts what can start.

        An import needs no guest, so its queue is followed apart from the runs': neither waits
        for the other's analysis to end.
        """
        started: list[asyncio.Task[None]] = []
        for kind in (AnalysisKind.RUN, AnalysisKind.IMPORTED):
            started += await self._tick(kind)
        return started

    async def _tick(self, kind: AnalysisKind) -> list[asyncio.Task[None]]:
        followers: list[asyncio.Task[None]] = []
        try:
            async with self._session_factory() as session:
                active = await get_active_analyses(session, kind)
                started = (self._follow_in_own_task(analysis.id) for analysis in active)
                followers.extend(task for task in started if task is not None)
                await self._start_startable(session, kind)
        except Exception:
            logger.exception("Runner tick failed")
        return followers

    def _follow_in_own_task(self, analysis_id: int) -> asyncio.Task[None] | None:
        """None when a task is already on the analysis; it then follows once more when it is done,
        so a nudge that arrives during a slow step is not lost.
        """
        if analysis_id in self._followers:
            self._follow_again.add(analysis_id)
            return None
        follower = asyncio.create_task(
            self._follow_until_settled(analysis_id), name=f"follow-analysis-{analysis_id}"
        )
        self._followers[analysis_id] = follower
        follower.add_done_callback(lambda _: self._followers.pop(analysis_id, None))
        return follower

    async def _follow_until_settled(self, analysis_id: int) -> None:
        while True:
            self._follow_again.discard(analysis_id)
            await self._follow_once(analysis_id)
            if analysis_id not in self._follow_again:
                return

    async def _follow_once(self, analysis_id: int) -> None:
        try:
            async with self._session_factory() as session:
                analysis = await get_analysis(session, analysis_id)
                if analysis is not None and analysis.status in ACTIVE_STATUSES:
                    await self._track_guarded(session, analysis)
        except Exception:
            logger.exception("Following analysis %s failed", analysis_id)

    async def _start_startable(self, session: AsyncSession, kind: AnalysisKind) -> None:
        while (queued := await get_oldest_startable_analysis(session, kind)) is not None:
            if not await claim_queued(session, queued.id):
                continue
            # The claim is a bulk UPDATE the session did not see; without a refresh the
            # object still says `queued` and a later write of `queued` would be skipped.
            await session.refresh(queued)
            await self._submit_guarded(session, queued)
            if queued.status is AnalysisStatus.QUEUED:
                # Sent back because CAPE or the control service is unreachable; trying the
                # next row now would start it ahead of this one.
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
        if is_memory_image_import(claimed):
            await self._follow_memory_image(session, claimed)
            return
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
                options=_task_options(options, interactive),
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
        if is_memory_image_import(analysis):
            await self._follow_memory_image(session, analysis)
            return
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
                analysis_id,
                report_file,
                started_at=_capture_start(analysis),
                archive_entry=analysis.options.get("archive_entry"),
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
            max_severity=_highest(outcome.max_severity, indexed.max_alert_severity),
            detected_families=outcome.detected_families,
            summary={
                **_with_entry_sha256(outcome.summary, indexed.entry_sha256),
                "lane_counts": indexed.lane_counts,
                "defender": _dumped(indexed.defender),
                "hidden_events": indexed.hidden_events,
                **({} if memory is None else {"memory": memory.model_dump(mode="json")}),
            },
            event_count=indexed.event_count,
        )

    async def _follow_memory_image(self, session: AsyncSession, analysis: Analysis) -> None:
        """Starts the scan of an image's upload unless this runner is already on it.

        The scan takes about a minute and has no CAPE task to poll, so it runs beside the ticks,
        which would otherwise hold up the runs' queue. A scan the previous runner left behind
        (`running` in the database, nothing in `_memory_imports`) is started again.
        """
        if analysis.id in self._memory_imports:
            return
        started_at = utc_now() if analysis.started_at is None else as_utc(analysis.started_at)
        if analysis.started_at is None or analysis.status is not AnalysisStatus.RUNNING:
            await update_analysis(
                session, analysis.id, status=AnalysisStatus.RUNNING, started_at=started_at
            )
        self._memory_imports[analysis.id] = asyncio.create_task(
            self._import_memory_image(analysis.id, started_at), name=f"memory-image-{analysis.id}"
        )

    async def _import_memory_image(self, analysis_id: int, started_at: datetime) -> None:
        try:
            await self._finish_memory_image(analysis_id, started_at)
        except Exception:
            logger.exception("Analysing the memory image of analysis %s failed", analysis_id)
        finally:
            self._memory_imports.pop(analysis_id, None)

    async def _finish_memory_image(self, analysis_id: int, started_at: datetime) -> None:
        try:
            imported = await self._images.run(analysis_id, started_at)
        except MemoryImportFailedError as failed:
            ending: AnalysisChanges = {"status": AnalysisStatus.FAILED, "error": str(failed)}
        except IngestFailedError as failure:
            ending = {
                "status": AnalysisStatus.REPORT_FAILED,
                "error": str(failure),
                "event_count": 0,
            }
        else:
            async with self._session_factory() as session:
                await self._finish_done(
                    session, analysis_id, IMAGE_OUTCOME, imported.indexed, imported.memory
                )
            return
        async with self._session_factory() as session:
            await self._finish(session, analysis_id, **ending)

    def _start_live_if_running(self, analysis: Analysis, task_id: int) -> None:
        if (
            analysis.kind is not AnalysisKind.RUN
            or analysis.status is not AnalysisStatus.RUNNING
            or analysis.started_at is None
            or analysis.id in self._collecting
        ):
            return
        try:
            self._live.start(analysis.id, task_id, analysis.started_at)
        except Exception:
            logger.exception("Starting the live collection of analysis %s failed", analysis.id)
        else:
            self._collecting.add(analysis.id)

    async def _stop_live(self, analysis_id: int) -> None:
        """Drains and ends the collection before the status moves on, so the final ingest never
        races the collector; a collector that fails or hangs is abandoned, never fatal."""
        if analysis_id not in self._collecting:
            return
        self._collecting.discard(analysis_id)
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


def _highest(*severities: Severity | None) -> Severity | None:
    return max((s for s in severities if s is not None), key=SEVERITY_ORDER.index, default=None)


def _dumped(verdict: DefenderVerdict | None) -> dict[str, Any] | None:
    return None if verdict is None else verdict.model_dump(mode="json")


def _with_entry_sha256(summary: dict[str, Any], sha256: str | None) -> dict[str, Any]:
    if sha256 is None:
        return summary
    return {**summary, "sample": {**summary.get("sample", {}), "entry_sha256": sha256}}


def _task_options(options: Mapping[str, Any], interactive: InteractiveOptions) -> str:
    parts = (_archive_options(options), interactive.options)
    return ",".join(part for part in parts if part)


def _archive_options(options: Mapping[str, Any]) -> str:
    password, entry = options.get("archive_password"), options.get("archive_entry")
    if password is None or entry is None:
        return ""
    return f"password={password},file={entry}"


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
