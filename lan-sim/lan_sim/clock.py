"""The two clocks the daemon reads, behind one interface so tests can set the time."""

import time
from datetime import UTC, datetime
from typing import Protocol


class Clock(Protocol):
    def now(self) -> datetime:
        """The wall-clock time, timezone-aware UTC, for event timestamps."""
        ...

    def monotonic(self) -> float:
        """Seconds that never go backwards, for durations and rate windows."""
        ...


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)

    def monotonic(self) -> float:
        return time.monotonic()
