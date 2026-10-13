"""The seams between the parts of M1a that are built separately.

The runner (tracks an analysis through CAPE) depends only on these, so it can be tested with
fakes, and the sample store and the report reader implement them without importing the runner.
"""

from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from app.db.models.analysis import Severity


class SampleSource(Protocol):
    """Hands out a plain copy of a stored sample, for uploading to CAPE.

    Samples rest encrypted; the copy exists only inside the `async with` block.
    """

    def open_plain(self, sha256: str) -> AbstractAsyncContextManager[Path]: ...


class ReportUnreadable(Exception):
    """The report is missing or is not a CAPE report; the message says which."""


@dataclass(frozen=True)
class ReportOutcome:
    score: float | None
    max_severity: Severity | None
    detected_families: list[str]
    summary: dict[str, Any]


ReportReader = Callable[[Path], ReportOutcome]
"""Reads a CAPE `report.json`; raises `ReportUnreadable` instead of returning partial data."""


class RunnerControl(Protocol):
    """What the API may ask of the runner."""

    def nudge(self) -> None:
        """Check for work now instead of at the next poll. Never blocks and never raises."""
