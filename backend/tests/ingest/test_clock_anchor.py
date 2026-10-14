"""The exact anchor of the guest clock: when CAPE's ResultServer logged a process registering."""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from app.ingest.clock import (
    ANCHOR_TOLERANCE,
    calibrated_offset,
    guest_clock_offset,
    host_registrations,
    read_host_registrations,
    task_log_of,
)
from tests.ingest.test_clock import report_with_clocks

CLOCK_FIXTURES = Path(__file__).parent.parent / "fixtures" / "cape" / "clock"
REAL_LOG = (CLOCK_FIXTURES / "task_45.cuckoo.log").read_text()

STARTED = datetime(2026, 10, 13, 15, 39, 23, tzinfo=UTC)
FIRST_SEEN = datetime(2026, 10, 13, 13, 39, 50, 393000, tzinfo=UTC)
REGISTERED = datetime(2026, 10, 13, 15, 39, 55, 690000, tzinfo=UTC)


def log_line(pid: int, at: str = "2026-10-13 15:39:55,690", task: int = 45) -> str:
    return (
        f"{at} [lib.cuckoo.core.resultserver] INFO: Task {task}: Process {pid} "
        f"(parent 4336): benign.exe, path C:\\Users\\Analyst\\AppData\\Local\\Temp\\benign.exe"
    )


# --- reading the log ----------------------------------------------------------------------


def test_the_real_log_gives_the_host_time_of_each_registration() -> None:
    assert host_registrations(REAL_LOG) == {
        9708: datetime(2026, 10, 13, 15, 39, 55, 690000, tzinfo=UTC),
        2476: datetime(2026, 10, 13, 15, 39, 56, 350000, tzinfo=UTC),
    }


def test_the_real_log_of_an_interactive_run_lists_every_process() -> None:
    registrations = host_registrations((CLOCK_FIXTURES / "task_133.cuckoo.log").read_text())
    assert len(registrations) == 12
    assert registrations[1768] == datetime(2026, 10, 13, 22, 49, 54, 400000, tzinfo=UTC)


def test_the_first_registration_of_a_reused_pid_wins() -> None:
    text = log_line(7, "2026-10-13 15:39:55,000") + "\n" + log_line(7, "2026-10-13 15:41:00,000")
    assert host_registrations(text) == {7: datetime(2026, 10, 13, 15, 39, 55, tzinfo=UTC)}


SERVER = "[lib.cuckoo.core.resultserver]"


@pytest.mark.parametrize(
    "text",
    [
        "",
        "garbage\n\n\x00\x01",
        "2026-10-13 15:39:55,690 [root] INFO: Task 45: Process 9708 (parent 1): x.exe, path y",
        f"2026-10-13 15:39:55,690 {SERVER} INFO: Task 45: Process x (parent 1)",
        f"not a time {SERVER} INFO: Task 45: Process 9 (parent 1): a, path b",
        f"2026-13-45 99:99:99,000 {SERVER} INFO: Task 4: Process 9 (parent 1): a, path b",
        f"2026-10-13 15:39:55,690 {SERVER} WARNING: Task 45: Process 9 died",
    ],
)
def test_lines_that_are_not_registrations_are_ignored(text: str) -> None:
    assert host_registrations(text) == {}


def test_garbage_between_registrations_does_not_hide_them() -> None:
    text = f"junk\n{log_line(1)}\n\x00\x00\n{log_line(2, '2026-10-13 15:39:56,000')}\ntail"
    assert set(host_registrations(text)) == {1, 2}


def test_a_log_file_is_read_from_the_task_folder(tmp_path: Path) -> None:
    (tmp_path / "cuckoo.log").write_text(REAL_LOG)
    assert set(read_host_registrations(tmp_path / "cuckoo.log")) == {9708, 2476}


def test_a_missing_log_gives_no_registrations(tmp_path: Path) -> None:
    assert read_host_registrations(tmp_path / "cuckoo.log") == {}


def test_a_log_that_cannot_be_read_gives_no_registrations(tmp_path: Path) -> None:
    assert read_host_registrations(tmp_path) == {}
    (tmp_path / "cuckoo.log").write_bytes(b"\xff\xfe\x00 not utf-8 \xc3\x28")
    assert read_host_registrations(tmp_path / "cuckoo.log") == {}


def test_the_task_log_sits_two_levels_above_the_report() -> None:
    report = Path("/storage/analyses/45/reports/report.json")
    assert task_log_of(report) == Path("/storage/analyses/45/cuckoo.log")


# --- calibrating with it ------------------------------------------------------------------


def test_the_anchor_measures_the_whole_offset_to_the_millisecond() -> None:
    offset = calibrated_offset(STARTED, FIRST_SEEN, REGISTERED)
    assert offset == timedelta(hours=2, seconds=5, milliseconds=297)
    assert FIRST_SEEN + offset == REGISTERED


def test_without_an_anchor_the_offset_is_the_rounded_quarter_hour() -> None:
    assert calibrated_offset(STARTED, FIRST_SEEN, None) == timedelta(hours=2)
    assert calibrated_offset(STARTED, FIRST_SEEN) == timedelta(hours=2)


@pytest.mark.parametrize(
    "registered",
    [
        REGISTERED + ANCHOR_TOLERANCE + timedelta(seconds=10),
        REGISTERED - ANCHOR_TOLERANCE - timedelta(seconds=10),
        REGISTERED + timedelta(hours=2),
        REGISTERED - timedelta(days=1),
    ],
)
def test_an_anchor_that_disagrees_with_the_hour_level_offset_is_rejected(
    registered: datetime,
) -> None:
    assert calibrated_offset(STARTED, FIRST_SEEN, registered) == timedelta(hours=2)


def test_an_anchor_just_inside_the_tolerance_is_accepted() -> None:
    registered = FIRST_SEEN + timedelta(hours=2) + ANCHOR_TOLERANCE
    assert (
        calibrated_offset(STARTED, FIRST_SEEN, registered) == timedelta(hours=2) + ANCHOR_TOLERANCE
    )


def test_a_guest_in_utc_is_anchored_too() -> None:
    started = datetime(2026, 10, 13, 12, 12, 18, tzinfo=UTC)
    first_seen = datetime(2026, 10, 13, 12, 12, 41, 164000, tzinfo=UTC)
    registered = first_seen + timedelta(seconds=5, milliseconds=746)
    assert calibrated_offset(started, first_seen, registered) == timedelta(
        seconds=5, milliseconds=746
    )


# --- in a report --------------------------------------------------------------------------


def report_of_task_45() -> dict[str, Any]:
    report = report_with_clocks(
        "2026-10-13 15:39:23", "2026-10-13 13:39:50,393", "2026-10-13 13:39:51,054"
    )
    report["behavior"]["processes"][0]["process_id"] = 9708
    report["behavior"]["processes"][1]["process_id"] = 2476
    return report


def test_a_report_is_calibrated_by_the_earliest_process_the_log_knows() -> None:
    registrations = host_registrations(REAL_LOG)
    assert guest_clock_offset(report_of_task_45(), registrations) == timedelta(
        hours=2, seconds=5, milliseconds=297
    )


def test_processes_the_log_does_not_know_are_skipped() -> None:
    registrations = {2476: datetime(2026, 10, 13, 15, 39, 56, 350000, tzinfo=UTC)}
    assert guest_clock_offset(report_of_task_45(), registrations) == timedelta(
        hours=2, seconds=5, milliseconds=296
    )


def test_a_report_without_registrations_keeps_the_rounded_offset() -> None:
    assert guest_clock_offset(report_of_task_45()) == timedelta(hours=2)
    assert guest_clock_offset(report_of_task_45(), {}) == timedelta(hours=2)


def test_a_log_of_other_pids_keeps_the_rounded_offset() -> None:
    assert guest_clock_offset(report_of_task_45(), {1: REGISTERED}) == timedelta(hours=2)


def test_a_report_that_cannot_be_calibrated_has_no_offset_even_with_a_log() -> None:
    assert guest_clock_offset({}, {9708: REGISTERED}) == timedelta(0)
