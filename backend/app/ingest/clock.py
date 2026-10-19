"""The two clocks in a CAPE report, and how to bring them onto one.

True UTC is the host's: `info.started`/`ended` and the epoch floats of `network.*`. capemon
stamps calls and `behavior.processes[].first_seen` with the guest monitor's clock, which runs
behind by the host's own UTC offset (2 hours in summer, 1 in winter in Warsaw) plus a few
seconds of skew (the guest's clock is set to the task's creation time, not the moment it was
set). Both are measured per analysis, never assumed.

The hour-level part comes from `info.started`, rounded to a quarter hour. The skew is exact
when the host's own record of a process registering with CAPE's ResultServer (a line of the
task's `cuckoo.log`, millisecond host time) can be matched with that process's guest
`first_seen`: the skew is constant within a run (7.143 to 7.147 s over 140 s on the longest
real one) and varies between runs (4.4 to 7.1 s).
"""

import math
import re
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from app.ingest.protocol import IngestContext
from app.ingest.reading import mapping_list, section, to_int
from app.ingest.windows_events import read_windows_events

OFFSET_GRANULARITY = timedelta(minutes=15)
MAX_PLAUSIBLE_OFFSET = timedelta(hours=14)
ANCHOR_TOLERANCE = timedelta(minutes=5)
TASK_LOG_NAME = "cuckoo.log"
# The guest-side logs a run leaves, in the order they are asked for the clock.
GUEST_LOG_EXPORTS = (("sysmon", "sysmon.xml"), ("aux", "defender.xml"))

_REGISTRATION = re.compile(
    r"^(?P<time>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3}) \[lib\.cuckoo\.core\.resultserver\] "
    r"INFO: Task \d+: Process (?P<pid>\d+) \(parent \d+\)"
)


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


def host_registrations(log_text: str) -> dict[int, datetime]:
    """When the host's ResultServer logged each process registering, from a task's `cuckoo.log`.

    The host clock is UTC. A pid that registers twice keeps its first time. Lines that are not
    registrations are skipped.
    """
    registered: dict[int, datetime] = {}
    for line in log_text.splitlines():
        match = _REGISTRATION.match(line)
        moment = parse_clock(match["time"].replace(",", ".")) if match else None
        if match and moment:
            registered.setdefault(int(match["pid"]), moment)
    return registered


def analysis_dir_of(report_path: Path) -> Path:
    """CAPE's folder of the task: the parent of its `reports/` folder."""
    return report_path.parent.parent


def task_log_of(report_path: Path) -> Path:
    """The task's `cuckoo.log` beside its `reports/` folder."""
    return analysis_dir_of(report_path) / TASK_LOG_NAME


def read_host_registrations(log_path: Path) -> dict[int, datetime]:
    """`host_registrations` of a file; empty when the file is missing or unreadable."""
    try:
        return host_registrations(log_path.read_text(errors="replace"))
    except OSError:
        return {}


def _processes_by_start(report: Mapping[str, Any]) -> list[tuple[datetime, int]]:
    entries = mapping_list(section(report, "behavior").get("processes"))
    starts = [
        (start, to_int(entry.get("process_id")) or 0)
        for entry in entries
        if (start := parse_clock(entry.get("first_seen")))
    ]
    return sorted(starts, key=lambda start: start[0])


def _quarter_hours_between(true_time: datetime, guest_time: datetime) -> timedelta | None:
    """The gap rounded to a quarter hour; `None` when it is no timezone's."""
    offset = round((true_time - guest_time) / OFFSET_GRANULARITY) * OFFSET_GRANULARITY
    return None if abs(offset) > MAX_PLAUSIBLE_OFFSET else offset


def calibrated_offset(
    started: datetime, first_process: datetime, registered_at: datetime | None = None
) -> timedelta:
    """What to add to a capemon timestamp to get UTC, from the true start and the first process.

    `started` is when the machine started and the first process appears seconds later, so the
    raw gap is the true offset minus those seconds; rounding to a quarter hour (real zones are
    whole quarters) removes them. Zero when the gap is no timezone's.

    `registered_at` is the host time at which that same process registered with CAPE: the
    difference to its guest time is the whole offset, skew included. It is used only when it
    agrees with the rounded offset to within `ANCHOR_TOLERANCE`; otherwise the rounded one stands.
    """
    offset = _quarter_hours_between(started, first_process)
    if offset is None:
        return timedelta(0)
    if (
        registered_at is not None
        and abs(registered_at - first_process - offset) <= ANCHOR_TOLERANCE
    ):
        return registered_at - first_process
    return offset


def _offset_from_processes(
    report: Mapping[str, Any], registrations: Mapping[int, datetime] | None
) -> timedelta | None:
    """The offset the report's monitored processes give; `None` when it lists none."""
    processes = _processes_by_start(report)
    if not processes:
        return None
    started = analysis_started(report)
    if started is None:
        return timedelta(0)
    known = registrations or {}
    first_seen, pid = next(((start, pid) for start, pid in processes if pid in known), processes[0])
    return calibrated_offset(started, first_seen, known.get(pid))


def guest_clock_offset(
    report: Mapping[str, Any], registrations: Mapping[int, datetime] | None = None
) -> timedelta:
    """The offset of a report's capemon clock; zero when the report cannot say.

    `registrations` (`host_registrations`) anchors it exactly on the earliest process the log
    knows.
    """
    offset = _offset_from_processes(report, registrations)
    return timedelta(0) if offset is None else offset


def analysis_clock_offset(report: Mapping[str, Any], context: IngestContext) -> timedelta:
    """The offset of the guest clock for the sources that read a guest log (Sysmon, Defender).

    It is `guest_clock_offset` whenever capemon monitored a process. When it monitored none (a
    sample Defender removed before it ran) there is no process to anchor on, so the clock is read
    off the guest's own log: its last record was written seconds before the analysis ended, and
    the gap rounds to the same quarter-hour granularity. Zero when that cannot be said.
    """
    offset = _offset_from_processes(report, context.host_registrations)
    if offset is not None:
        return offset
    ended = analysis_ended(report)
    latest = _latest_guest_log_time(context.analysis_dir) if ended is not None else None
    if ended is None or latest is None:
        return timedelta(0)
    return _quarter_hours_between(ended, latest) or timedelta(0)


def _latest_guest_log_time(analysis_dir: Path | None) -> datetime | None:
    if analysis_dir is None:
        return None
    for parts in GUEST_LOG_EXPORTS:
        written = (
            event.system_time
            for event in read_windows_events(analysis_dir.joinpath(*parts))
            if event.system_time is not None
        )
        if (latest := max(written, default=None)) is not None:
            return latest
    return None
