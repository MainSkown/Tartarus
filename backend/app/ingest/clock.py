"""The two clocks in a CAPE report, and how to bring them onto one.

True UTC is the host's: `info.started`/`ended` and the epoch floats of `network.*`. capemon
stamps calls and `behavior.processes[].first_seen` with the guest monitor's clock, which runs
behind by the host's own UTC offset (2 hours in summer, 1 in winter in Warsaw), so the offset is
measured per report, never assumed.
"""

import math
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

from app.ingest.reading import mapping_list, section

OFFSET_GRANULARITY = timedelta(minutes=15)
MAX_PLAUSIBLE_OFFSET = timedelta(hours=14)


def parse_clock(value: object) -> datetime | None:
    """CAPE's text timestamps (`2026-10-13 10:12:41,164`, `... 12:12:18`); naive means UTC."""
    if not isinstance(value, str):
        return None
    try:
        moment = datetime.fromisoformat(value.replace(",", "."))
    except ValueError:
        return None
    return moment.replace(tzinfo=UTC) if moment.tzinfo is None else moment.astimezone(UTC)


def epoch_to_datetime(value: object) -> datetime | None:
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value):
        return None
    try:
        return datetime.fromtimestamp(value, UTC)
    except (OverflowError, OSError, ValueError):
        return None


def _info_time(report: Mapping[str, Any], key: str) -> datetime | None:
    return parse_clock(section(report, "info").get(key))


def analysis_started(report: Mapping[str, Any]) -> datetime | None:
    return _info_time(report, "started")


def analysis_ended(report: Mapping[str, Any]) -> datetime | None:
    return _info_time(report, "ended")


def _earliest_process_start(report: Mapping[str, Any]) -> datetime | None:
    entries = mapping_list(section(report, "behavior").get("processes"))
    starts = [start for entry in entries if (start := parse_clock(entry.get("first_seen")))]
    return min(starts, default=None)


def calibrated_offset(started: datetime, first_process: datetime) -> timedelta:
    """What to add to a capemon timestamp to get UTC, from the true start and the first process.

    `started` is when the machine started and the first process appears seconds later, so the
    raw gap is the true offset minus those seconds; rounding to a quarter hour (real zones are
    whole quarters) removes them. Zero when the gap is no timezone's.
    """
    offset = round((started - first_process) / OFFSET_GRANULARITY) * OFFSET_GRANULARITY
    return offset if abs(offset) <= MAX_PLAUSIBLE_OFFSET else timedelta(0)


def guest_clock_offset(report: Mapping[str, Any]) -> timedelta:
    """The offset of a report's capemon clock; zero when the report cannot say."""
    started = analysis_started(report)
    first_process = _earliest_process_start(report)
    if started is None or first_process is None:
        return timedelta(0)
    return calibrated_offset(started, first_process)
