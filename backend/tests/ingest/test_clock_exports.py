from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from app.ingest.clock import analysis_clock_offset
from app.ingest.protocol import IngestContext
from tests.ingest import defender_cases
from tests.ingest.sysmon_cases import analysis_with, event_xml
from tests.ingest.test_clock import report_with_clocks

STARTED = datetime(2026, 10, 18, 14, 34, 42, tzinfo=UTC)
ENDED = "2026-10-18 14:35:11"
LATEST_GUEST_TIME = "2026-10-18 12:34:49.400"


def context_of(root: Path | None) -> IngestContext:
    return IngestContext(analysis_id=1, started_at=STARTED, analysis_dir=root)


def sysmon_log(root: Path, *guest_times: str) -> Path:
    return analysis_with(
        root, *(event_xml(11, number, time, {}) for number, time in enumerate(guest_times, 1))
    )


def defender_log(root: Path, *system_times: str) -> Path:
    events = (
        defender_cases.event_xml(5007, number, time.replace(" ", "T") + "Z", {})
        for number, time in enumerate(system_times, 1)
    )
    return defender_cases.write_export(root, defender_cases.export_xml(*events))


def blind_report(ended: str | None = ENDED) -> dict[str, Any]:
    report = report_with_clocks("2026-10-18 14:34:42")
    if ended is not None:
        report["info"]["ended"] = ended
    return report


def test_without_a_monitored_process_the_last_sysmon_record_is_seconds_before_the_end(
    tmp_path: Path,
) -> None:
    root = sysmon_log(
        tmp_path, "2026-10-18 12:28:35.000", LATEST_GUEST_TIME, "2026-10-18 12:30:00.000"
    )

    assert analysis_clock_offset(blind_report(), context_of(root)) == timedelta(hours=2)


def test_the_export_in_the_other_direction_gives_a_negative_offset(tmp_path: Path) -> None:
    root = sysmon_log(tmp_path, "2026-10-18 16:34:49.400")

    assert analysis_clock_offset(blind_report(), context_of(root)) == timedelta(hours=-2)


def test_the_defender_export_stands_in_when_there_is_no_sysmon_file(tmp_path: Path) -> None:
    root = defender_log(tmp_path, "2026-10-18 12:28:35", "2026-10-18 12:34:59")

    assert analysis_clock_offset(blind_report(), context_of(root)) == timedelta(hours=2)


def test_the_sysmon_export_wins_over_the_defender_one(tmp_path: Path) -> None:
    root = sysmon_log(tmp_path, LATEST_GUEST_TIME)
    defender_log(root, "2026-10-18 13:34:59")

    assert analysis_clock_offset(blind_report(), context_of(root)) == timedelta(hours=2)


def test_an_empty_sysmon_export_falls_through_to_the_defender_one(tmp_path: Path) -> None:
    root = sysmon_log(tmp_path)
    defender_log(root, "2026-10-18 12:34:59")

    assert analysis_clock_offset(blind_report(), context_of(root)) == timedelta(hours=2)


def test_a_report_with_monitored_processes_keeps_its_own_offset(tmp_path: Path) -> None:
    root = sysmon_log(tmp_path, "2026-10-18 09:00:00.000")
    report = report_with_clocks("2026-10-18 14:34:42", "2026-10-18 12:34:55")
    report["info"]["ended"] = ENDED

    assert analysis_clock_offset(report, context_of(root)) == timedelta(hours=2)


def test_a_utc_guest_with_monitored_processes_is_not_second_guessed_by_the_export(
    tmp_path: Path,
) -> None:
    root = sysmon_log(tmp_path, "2026-10-18 12:34:49.400")
    report = report_with_clocks("2026-10-18 14:34:42", "2026-10-18 14:34:55")
    report["info"]["ended"] = ENDED

    assert analysis_clock_offset(report, context_of(root)) == timedelta(0)


def test_it_is_zero_without_an_end_to_measure_against(tmp_path: Path) -> None:
    root = sysmon_log(tmp_path, LATEST_GUEST_TIME)

    assert analysis_clock_offset(blind_report(ended=None), context_of(root)) == timedelta(0)


def test_it_is_zero_without_an_analysis_folder_or_an_export(tmp_path: Path) -> None:
    assert analysis_clock_offset(blind_report(), context_of(None)) == timedelta(0)
    assert analysis_clock_offset(blind_report(), context_of(tmp_path)) == timedelta(0)


def test_it_is_zero_when_no_record_of_the_export_has_a_time(tmp_path: Path) -> None:
    root = analysis_with(tmp_path, "<Event><System><EventID>11</EventID></System></Event>")

    assert analysis_clock_offset(blind_report(), context_of(root)) == timedelta(0)


def test_a_gap_no_timezone_has_is_zero(tmp_path: Path) -> None:
    root = sysmon_log(tmp_path, "2026-09-01 00:00:00.000")

    assert analysis_clock_offset(blind_report(), context_of(root)) == timedelta(0)
