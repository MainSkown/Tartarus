import json
from pathlib import Path
from typing import Any

import pytest

from app.analyses.ports import ReportUnreadableError
from app.analyses.summary import ReportSummary, read_report
from app.db.models.analysis import Severity

# Derived from a real CAPE run of the benign test sample (tests/samples), with the call lists,
# environment blocks, PE details and most of the network capture removed.
TRIMMED_REPORT = Path(__file__).parent / "fixtures" / "cape" / "report_trimmed.json"


def write_report(directory: Path, report: Any) -> Path:
    path = directory / "report.json"
    path.write_text(json.dumps(report))
    return path


def signature(name: str, severity: int) -> dict[str, Any]:
    return {"name": name, "severity": severity, "description": f"{name} happened"}


def read_signatures(tmp_path: Path, *signatures: dict[str, Any]) -> Any:
    return read_report(write_report(tmp_path, {"info": {}, "signatures": list(signatures)}))


def test_a_real_report_yields_score_severity_and_no_families() -> None:
    outcome = read_report(TRIMMED_REPORT)

    assert outcome.score == 6.0
    assert outcome.max_severity is Severity.HIGH
    assert outcome.detected_families == []


def test_a_real_report_summary_describes_the_run() -> None:
    summary = ReportSummary.model_validate(read_report(TRIMMED_REPORT).summary)

    assert summary.duration_s == 55
    assert summary.process_count == 2
    assert summary.sample.name == "benign.exe"
    assert summary.sample.type == "PE32+ executable (console) x86-64, for MS Windows"
    assert summary.files_written == 1
    assert summary.registry_keys_written == 2
    assert summary.network.dns == 5
    assert summary.network.tcp == 20
    assert summary.network.hosts == 0


def test_signatures_list_the_most_severe_first_with_the_design_systems_scale() -> None:
    summary = ReportSummary.model_validate(read_report(TRIMMED_REPORT).summary)

    assert len(summary.signatures) == 12
    assert summary.signatures[0].name == "recon_systeminfo"
    assert summary.signatures[0].severity is Severity.HIGH
    assert summary.signatures[0].description
    severities = [item.severity for item in summary.signatures]
    assert severities == sorted(severities, key=list(Severity).index, reverse=True)


def test_techniques_are_unique_and_name_the_signatures_that_raised_them() -> None:
    summary = ReportSummary.model_validate(read_report(TRIMMED_REPORT).summary)

    by_id = {technique.id: technique.signatures for technique in summary.techniques}
    assert len(by_id) == len(summary.techniques)
    assert by_id["T1574"] == ["dllload_suspicious_directory"]
    assert by_id["T1055"] == ["antianalysis_tls_section", "pe_tls_callbacks"]


def test_the_summary_is_plain_json_and_carries_no_call_data() -> None:
    summary = read_report(TRIMMED_REPORT).summary

    assert json.loads(json.dumps(summary)) == summary
    assert "calls" not in json.dumps(summary)


@pytest.mark.parametrize(
    ("cape_severity", "expected"),
    [
        (0, Severity.INFO),
        (1, Severity.LOW),
        (2, Severity.MEDIUM),
        (3, Severity.HIGH),
        (4, Severity.CRITICAL),
        (7, Severity.CRITICAL),
    ],
)
def test_cape_severity_maps_onto_the_design_system_scale(
    tmp_path: Path, cape_severity: int, expected: Severity
) -> None:
    outcome = read_signatures(tmp_path, signature("one", cape_severity))

    assert outcome.max_severity is expected
    assert ReportSummary.model_validate(outcome.summary).signatures[0].severity is expected


def test_max_severity_is_the_highest_among_signatures(tmp_path: Path) -> None:
    outcome = read_signatures(tmp_path, signature("a", 1), signature("b", 4), signature("c", 2))

    assert outcome.max_severity is Severity.CRITICAL


def test_a_report_without_signatures_has_no_max_severity(tmp_path: Path) -> None:
    outcome = read_signatures(tmp_path)

    assert outcome.max_severity is None
    assert ReportSummary.model_validate(outcome.summary).signatures == []


@pytest.mark.parametrize(
    ("detections", "expected"),
    [(["emotet", "qakbot"], ["emotet", "qakbot"]), (None, []), ([], [])],
)
def test_detected_families_come_from_a_detections_list(
    tmp_path: Path, detections: list[str] | None, expected: list[str]
) -> None:
    path = write_report(tmp_path, {"info": {}, "detections": detections})

    assert read_report(path).detected_families == expected


def test_a_minimal_report_reads_with_empty_defaults(tmp_path: Path) -> None:
    outcome = read_report(write_report(tmp_path, {"info": {}}))

    summary = ReportSummary.model_validate(outcome.summary)
    assert outcome.score is None
    assert summary.duration_s is None
    assert summary.process_count == 0
    assert summary.sample.name is None
    assert summary.network.dns == 0


def test_a_missing_report_is_unreadable_and_says_so(tmp_path: Path) -> None:
    with pytest.raises(ReportUnreadableError, match="missing"):
        read_report(tmp_path / "report.json")


def test_invalid_json_is_unreadable_and_says_so(tmp_path: Path) -> None:
    path = tmp_path / "report.json"
    path.write_text('{"info": {')

    with pytest.raises(ReportUnreadableError, match="not valid JSON"):
        read_report(path)


@pytest.mark.parametrize("content", [[], {"signatures": []}, {"info": "nope"}])
def test_json_that_is_not_a_cape_report_is_unreadable_and_says_so(
    tmp_path: Path, content: Any
) -> None:
    with pytest.raises(ReportUnreadableError, match="not a CAPE report"):
        read_report(write_report(tmp_path, content))
