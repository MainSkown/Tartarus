"""The seams between the parts of M1a that are built separately.

The runner (tracks an analysis through CAPE) depends only on these, so it can be tested with
fakes, and the sample store and the report reader implement them without importing the runner.
"""

from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol

from app.analyses.defender import DefenderVerdict
from app.db.models.analysis import Severity
from app.guest.schemas import Guest, GuestProfile, MemoryAnalysis


class SampleSource(Protocol):
    """Hands out a plain copy of a stored sample, for uploading to CAPE.

    Samples rest encrypted; the copy exists only inside the `async with` block.
    """

    def open_plain(self, sha256: str) -> AbstractAsyncContextManager[Path]: ...


class ReportUnreadableError(Exception):
    """The report is missing or is not a CAPE report; the message says which."""


@dataclass(frozen=True)
class ReportOutcome:
    score: float | None
    max_severity: Severity | None
    detected_families: list[str]
    summary: dict[str, Any]


ReportReader = Callable[[Path], ReportOutcome]
"""Reads a CAPE `report.json`; raises `ReportUnreadableError` instead of returning partial data."""


class IngestFailedError(Exception):
    """The events could not be indexed; the message says why. The analysis ends `report_failed`."""


@dataclass(frozen=True)
class IngestResult:
    """What an ingest learned. `defender` is None only when the ingester ran without a Defender
    normaliser; with one it is always a verdict, `no_export` when the guest left no export.
    `hidden_events` counts the Sysmon events left out as background, by reason; empty when
    there was no Sysmon file.
    """

    event_count: int
    lane_counts: dict[str, int]
    defender: DefenderVerdict | None = None
    hidden_events: dict[str, int] = field(default_factory=dict)


class EventIngester(Protocol):
    """Indexes a finished report's events for one analysis, replacing any earlier index."""

    async def ingest(
        self, analysis_id: int, report_path: Path, *, started_at: datetime | None = None
    ) -> IngestResult:
        """Raises `IngestFailedError`, leaving no index behind, when the events cannot be stored.

        `started_at` replaces the report's own start, for a capture imported long after it was
        taken.
        """


class MemoryControl(Protocol):
    """The memory routes of the guest control service."""

    async def analyse_memory(self, task_id: int) -> MemoryAnalysis:
        """Raises `GuestControlRejected` with status 404 when the task has no dump on disk."""

    async def delete_memory_dump(self, task_id: int) -> None:
        """Raises `GuestControlRejected` with status 404 when the task has no dump on disk."""


class GuestSource(MemoryControl, Protocol):
    """What the runner asks the guest control service, to know where and how to run a task."""

    async def guest(self, name: str) -> Guest:
        """Raises `GuestControlRejected` with status 404 when no guest has that name."""

    async def profiles(self) -> list[GuestProfile]: ...

    async def finish_task(self, task_id: int, guest: str) -> None:
        """Ends the task's run in the guest; raises `GuestControlError` when it cannot."""


class RunnerControl(Protocol):
    """What the API may ask of the runner."""

    def nudge(self) -> None:
        """Check for work now instead of at the next poll. Never blocks and never raises."""


class LiveCollection(Protocol):
    """Follows a running analysis's logs for live viewing; the runner starts and stops it."""

    def start(self, analysis_id: int, cape_task_id: int, started_at: datetime) -> None:
        """Begins collecting; calling it again for the same analysis changes nothing."""

    async def stop(self, analysis_id: int) -> None:
        """Collects what is still unread and ends, so the final ingest sees a finished stream."""


class NoLiveCollection:
    """The port when nothing watches live."""

    def start(self, analysis_id: int, cape_task_id: int, started_at: datetime) -> None:
        pass

    async def stop(self, analysis_id: int) -> None:
        pass
