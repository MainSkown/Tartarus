import json
from pathlib import Path

import pytest

from app.analyses.missing_exports import MissingExport, export_warnings
from app.analyses.summary import ReportSummary, read_report

SYSMON = "Microsoft-Windows-Sysmon/Operational"
DEFENDER = "Microsoft-Windows-Windows Defender/Operational"
TIMED_OUT = (
    "the export failed: HTTPConnectionPool(host='192.168.150.14', port=8000): "
    "Read timed out. (read timeout={seconds})"
)


def missing(channel: str, reason: str) -> MissingExport:
    return MissingExport(channel=channel, reason=reason)


def test_a_sysmon_export_that_timed_out_is_a_warning_naming_the_channel_and_the_wait() -> None:
    warnings = export_warnings([missing(SYSMON, TIMED_OUT.format(seconds=120))])

    assert warnings == ["Sysmon events were not exported: the guest did not answer within 120 s"]


def test_each_failed_channel_gets_its_own_warning() -> None:
    warnings = export_warnings(
        [
            missing(SYSMON, TIMED_OUT.format(seconds=120)),
            missing(DEFENDER, TIMED_OUT.format(seconds=30)),
        ]
    )

    assert warnings == [
        "Sysmon events were not exported: the guest did not answer within 120 s",
        "Windows Defender events were not exported: the guest did not answer within 30 s",
    ]


def test_a_guest_agent_that_never_answered_says_how_long_the_module_waited() -> None:
    reason = "the guest agent did not answer within 60 s (HTTPConnectionPool: Max retries exceeded)"

    assert export_warnings([missing(SYSMON, reason)]) == [
        "Sysmon events were not exported: the guest agent did not answer within 60 s"
    ]


def test_a_reason_in_no_known_shape_is_kept_as_it_was_written() -> None:
    reason = "the guest did not return an Events document; nothing written"

    assert export_warnings([missing(DEFENDER, reason)]) == [
        f"Windows Defender events were not exported: {reason}"
    ]


def test_a_channel_the_table_does_not_know_is_named_as_the_module_wrote_it() -> None:
    assert export_warnings([missing("Some/Channel", "boom")]) == [
        "Some/Channel events were not exported: boom"
    ]


def test_nothing_missing_is_no_warning() -> None:
    assert export_warnings([]) == []


def analysis_report(tmp_path: Path) -> Path:
    reports = tmp_path / "analysis" / "reports"
    reports.mkdir(parents=True)
    path = reports / "report.json"
    path.write_text(json.dumps({"info": {}}))
    return path


def write_marker(report: Path, *entries: dict[str, str]) -> None:
    marker = report.parent.parent / "aux" / "event_logs.json"
    marker.parent.mkdir(exist_ok=True)
    marker.write_text(json.dumps({"missing": list(entries)}))


def warnings_of(report: Path) -> list[str]:
    return ReportSummary.model_validate(read_report(report).summary).warnings


def test_the_summary_of_a_run_whose_sysmon_export_failed_carries_one_warning(
    tmp_path: Path,
) -> None:
    report = analysis_report(tmp_path)
    write_marker(report, {"channel": SYSMON, "reason": TIMED_OUT.format(seconds=120)})

    assert warnings_of(report) == [
        "Sysmon events were not exported: the guest did not answer within 120 s"
    ]


def test_the_summary_of_a_clean_run_carries_none(tmp_path: Path) -> None:
    assert warnings_of(analysis_report(tmp_path)) == []


def test_reading_the_same_run_again_gives_the_same_warnings_not_more(tmp_path: Path) -> None:
    report = analysis_report(tmp_path)
    write_marker(report, {"channel": SYSMON, "reason": TIMED_OUT.format(seconds=120)})

    first = warnings_of(report)
    second = warnings_of(report)

    assert first == second
    assert len(second) == 1


def test_a_marker_that_is_gone_on_the_next_ingest_leaves_no_warning_behind(tmp_path: Path) -> None:
    report = analysis_report(tmp_path)
    write_marker(report, {"channel": SYSMON, "reason": "boom"})
    assert warnings_of(report) != []

    (report.parent.parent / "aux" / "event_logs.json").unlink()

    assert warnings_of(report) == []


def test_a_summary_stored_before_warnings_existed_still_validates() -> None:
    assert ReportSummary.model_validate({"process_count": 2}).warnings == []


@pytest.mark.parametrize("content", ["not json", '{"missing": [1]}'])
def test_a_damaged_marker_gives_no_warning_rather_than_failing_the_ingest(
    tmp_path: Path, content: str
) -> None:
    report = analysis_report(tmp_path)
    marker = report.parent.parent / "aux" / "event_logs.json"
    marker.parent.mkdir()
    marker.write_text(content)

    assert warnings_of(report) == []
