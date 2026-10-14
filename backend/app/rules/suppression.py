from dataclasses import dataclass
from datetime import datetime, timedelta

type WindowKey = tuple[str, str | None]


@dataclass
class _Window:
    closes_at: datetime
    detection_id: str
    repeated: int = 0


class Suppression:
    """One open window per key. Windows open when a detection is emitted and do not slide.

    Time is whatever the caller passes, which is the event's own time, so a live run and a
    final ingest of the same events suppress the same ones. Events must arrive in time order.
    """

    def __init__(self, window: timedelta) -> None:
        self._window = window
        self._open: dict[WindowKey, _Window] = {}

    def repeat(self, key: WindowKey, moment: datetime) -> tuple[str, int] | None:
        """Counts a repeat; returns `(detection id, repeats so far)` if `key` has an open window."""
        window = self._open.get(key)
        if window is None or moment >= window.closes_at:
            return None
        window.repeated += 1
        return window.detection_id, window.repeated

    def open(self, key: WindowKey, moment: datetime, detection_id: str) -> None:
        self._open[key] = _Window(moment + self._window, detection_id)
