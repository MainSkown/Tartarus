from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from app.ingest.clock import (
    analysis_ended,
    analysis_started,
    epoch_to_datetime,
    guest_clock_offset,
    parse_clock,
)
from tests.ingest.reports import report_of


def report_with_clocks(started: str, *first_seen: str) -> dict[str, Any]:
    processes = [{"process_id": pid, "first_seen": text} for pid, text in enumerate(first_seen, 1)]
    report = report_of(*processes)
    report["info"] = {"started": started}
    return report


@pytest.mark.parametrize(
    ("first_seen", "expected_hours"),
    [
        ("2026-10-13 10:12:41,164", 2),
        ("2026-10-13 11:12:38,000", 1),
        ("2026-10-13 12:12:20,000", 0),
        ("2026-10-13 14:12:28,000", -2),
        ("2026-10-13 06:42:41,000", 5.5),
    ],
)
def test_the_offset_is_the_gap_to_info_started_rounded_to_a_quarter_hour(
    first_seen: str, expected_hours: float
) -> None:
    report = report_with_clocks("2026-10-13 12:12:18", first_seen)
    assert guest_clock_offset(report) == timedelta(hours=expected_hours)


def test_the_real_gap_of_two_hours_less_the_boot_time_rounds_to_two_hours() -> None:
    report = report_with_clocks("2026-10-13 12:12:18", "2026-10-13 10:12:41,164")
    assert guest_clock_offset(report) == timedelta(hours=2)


def test_the_earliest_process_decides() -> None:
    report = report_with_clocks(
        "2026-10-13 12:12:18", "2026-10-13 10:12:41,613", "2026-10-13 10:12:41,164"
    )
    assert guest_clock_offset(report) == timedelta(hours=2)


def test_a_process_without_a_readable_first_seen_is_ignored() -> None:
    report = report_with_clocks("2026-10-13 12:12:18", "garbage", "2026-10-13 11:12:30,000")
    assert guest_clock_offset(report) == timedelta(hours=1)


@pytest.mark.parametrize(
    "report",
    [
        {},
        {"info": None, "behavior": None},
        {"info": {"started": "2026-10-13 12:12:18"}},
        {"info": {"started": "2026-10-13 12:12:18"}, "behavior": {"processes": []}},
        {"info": {"started": "2026-10-13 12:12:18"}, "behavior": {"processes": "x"}},
        {"info": {"started": "2026-10-13 12:12:18"}, "behavior": {"processes": [None, 3]}},
        {"behavior": {"processes": [{"first_seen": "2026-10-13 10:12:41,164"}]}},
        {"info": {"started": "yesterday"}, "behavior": {"processes": [{"first_seen": "x"}]}},
        {"info": {"started": 5}, "behavior": {"processes": [{"first_seen": 7}]}},
        {"info": [], "behavior": []},
    ],
)
def test_a_report_that_cannot_be_calibrated_has_no_offset(report: dict[str, Any]) -> None:
    assert guest_clock_offset(report) == timedelta(0)


def test_a_gap_no_timezone_explains_is_treated_as_garbage() -> None:
    report = report_with_clocks("2026-10-13 12:12:18", "2026-10-11 12:12:18,000")
    assert guest_clock_offset(report) == timedelta(0)


def test_the_analysis_window_is_read_as_utc() -> None:
    report = {"info": {"started": "2026-10-13 12:12:18", "ended": "2026-10-13 12:13:13"}}
    assert analysis_started(report) == datetime(2026, 10, 13, 12, 12, 18, tzinfo=UTC)
    assert analysis_ended(report) == datetime(2026, 10, 13, 12, 13, 13, tzinfo=UTC)


@pytest.mark.parametrize("report", [{}, {"info": None}, {"info": {"started": "x"}}])
def test_a_missing_analysis_window_is_none(report: dict[str, Any]) -> None:
    assert analysis_started(report) is None
    assert analysis_ended(report) is None


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("2026-10-13 10:12:41,164", datetime(2026, 10, 13, 10, 12, 41, 164000, tzinfo=UTC)),
        ("2026-10-13 10:12:41.164", datetime(2026, 10, 13, 10, 12, 41, 164000, tzinfo=UTC)),
        ("2026-10-13T10:12:41+02:00", datetime(2026, 10, 13, 8, 12, 41, tzinfo=UTC)),
        ("2026-10-13 10:12:41", datetime(2026, 10, 13, 10, 12, 41, tzinfo=UTC)),
    ],
)
def test_parse_clock_reads_naive_text_as_utc(text: str, expected: datetime) -> None:
    assert parse_clock(text) == expected


@pytest.mark.parametrize("value", [None, 5, "", "garbage", ["2026-10-13"]])
def test_parse_clock_returns_none_for_what_it_cannot_read(value: object) -> None:
    assert parse_clock(value) is None


def test_epoch_seconds_become_utc() -> None:
    assert epoch_to_datetime(1791893546.015928) == datetime(
        2026, 10, 13, 12, 12, 26, 15928, tzinfo=UTC
    )


@pytest.mark.parametrize("value", [None, "1791893546", True, float("nan"), float("inf"), 1e30])
def test_epoch_to_datetime_returns_none_for_what_it_cannot_read(value: object) -> None:
    assert epoch_to_datetime(value) is None


def test_the_offset_is_two_hours_on_the_fixture(full_report: dict[str, Any]) -> None:
    assert guest_clock_offset(full_report) == timedelta(hours=2)
