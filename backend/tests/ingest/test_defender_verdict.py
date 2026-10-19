from pathlib import Path
from typing import Any

from app.ingest.defender import DefenderNormalizer
from app.ingest.defender_verdict import defender_verdict
from tests.ingest.defender_cases import (
    DROPPED_STARTED,
    DROPPED_TASK,
    DROPPER_IMAGE,
    EICAR_DETECTION,
    EICAR_SAMPLE_PATH,
    EICAR_STARTED,
    EICAR_TASK,
    closing_data,
    context_of,
    copy_export,
    detection_data,
    event_xml,
    export_xml,
    report_of,
    write_export,
)


def verdict_of(root: Path | None, *, process_count: int = 0) -> dict[str, Any]:
    report = report_of(EICAR_TASK, EICAR_STARTED)
    return defender_verdict(report, context_of(root, EICAR_STARTED), process_count)


def test_eicar_sample_removed_before_the_run_is_blocked_before_run(tmp_path: Path) -> None:
    root = copy_export(tmp_path, "defender-eicar-sample.xml")

    verdict = verdict_of(root, process_count=0)

    assert verdict["status"] == "removed"
    assert verdict["sample_removed"] is True
    assert verdict["blocked_before_run"] is True
    assert verdict["threats"] == [
        {
            "detection_id": EICAR_DETECTION,
            "threat_id": 2147519003,
            "name": "Virus:DOS/EICAR_Test_File",
            "severity": 4,
            "category_id": 42,
            "scope": "sample",
            "path": EICAR_SAMPLE_PATH,
            "process": r"C:\Python311\pythonw.exe",
            "user": "DESKTOP-2YK5XLK\\Alice",
            "detected_at": "2026-10-18T23:33:45.000Z",
            "action": "quarantine",
            "outcome": "removed",
            "removed_at": "2026-10-18T23:33:59.121Z",
        }
    ]


def test_sample_removed_after_processes_ran_is_not_blocked_before_run(tmp_path: Path) -> None:
    root = copy_export(tmp_path, "defender-eicar-sample.xml")

    verdict = verdict_of(root, process_count=3)

    assert verdict["sample_removed"] is True
    assert verdict["blocked_before_run"] is False


def test_dropped_file_removal_is_a_threat_but_not_the_sample(tmp_path: Path) -> None:
    root = copy_export(tmp_path, "defender-dropped-file.xml")
    report = report_of(DROPPED_TASK, DROPPED_STARTED, (DROPPER_IMAGE,))

    verdict = defender_verdict(report, context_of(root, DROPPED_STARTED), process_count=1)

    assert verdict["status"] == "removed"
    assert verdict["sample_removed"] is False
    assert verdict["blocked_before_run"] is False
    assert verdict["threats"] == [
        {
            "detection_id": "{DAF6711A-6D6D-406E-AADE-06C5B6A9E567}",
            "threat_id": 2147519003,
            "name": "Virus:DOS/EICAR_Test_File",
            "severity": 4,
            "category_id": 42,
            "scope": "dropped",
            "path": r"C:\Users\Public\tt-dropped-eicar.txt",
            "process": DROPPER_IMAGE,
            "user": "DESKTOP-2YK5XLK\\Alice",
            "detected_at": "2026-10-18T23:26:21.431Z",
            "action": "quarantine",
            "outcome": "removed",
            "removed_at": "2026-10-18T23:26:31.919Z",
        }
    ]


def test_tooling_only_export_is_clean(tmp_path: Path) -> None:
    root = copy_export(tmp_path, "defender-benign-tooling-only.xml")

    verdict = verdict_of(root)

    assert verdict == {
        "status": "clean",
        "sample_removed": False,
        "blocked_before_run": False,
        "threats": [],
    }


def test_defender_off_export_is_clean(tmp_path: Path) -> None:
    root = copy_export(tmp_path, "defender-off-guest.xml")

    assert verdict_of(root)["status"] == "clean"


def test_missing_export_is_no_export(tmp_path: Path) -> None:
    assert verdict_of(tmp_path)["status"] == "no_export"


def test_no_analysis_folder_is_no_export() -> None:
    assert verdict_of(None)["status"] == "no_export"


def test_detection_without_a_closing_event_is_detected_not_removed(tmp_path: Path) -> None:
    detected = event_xml(1116, 300, "2026-10-18T21:09:44.8Z", detection_data())
    root = write_export(tmp_path, export_xml(detected))

    verdict = verdict_of(root, process_count=0)

    assert verdict["status"] == "detected"
    assert verdict["sample_removed"] is False
    assert verdict["blocked_before_run"] is False
    assert verdict["threats"][0]["outcome"] == "pending"
    assert verdict["threats"][0]["action"] == "none"
    assert verdict["threats"][0]["removed_at"] is None


def test_failed_action_makes_the_status_failed(tmp_path: Path) -> None:
    detected = event_xml(1116, 300, "2026-10-18T21:09:44.8Z", detection_data())
    failed = event_xml(1118, 301, "2026-10-18T21:09:50.8Z", closing_data(action_id="2"))
    root = write_export(tmp_path, export_xml(detected, failed))

    verdict = verdict_of(root, process_count=0)

    assert verdict["status"] == "failed"
    assert verdict["sample_removed"] is False
    assert verdict["threats"][0]["outcome"] == "failed"


def test_unknown_action_is_not_a_removal(tmp_path: Path) -> None:
    detected = event_xml(1116, 300, "2026-10-18T21:09:44.8Z", detection_data())
    unknown = event_xml(1117, 301, "2026-10-18T21:09:50.8Z", closing_data(action_id="7"))
    root = write_export(tmp_path, export_xml(detected, unknown))

    verdict = verdict_of(root, process_count=0)

    assert verdict["status"] == "detected"
    assert verdict["threats"][0]["outcome"] == "pending"


def test_verdict_and_normaliser_agree_on_the_threats(tmp_path: Path) -> None:
    root = copy_export(tmp_path, "defender-dropped-file.xml")
    report = report_of(DROPPED_TASK, DROPPED_STARTED, (DROPPER_IMAGE,))
    context = context_of(root, DROPPED_STARTED)

    verdict = defender_verdict(report, context, process_count=1)
    events = list(DefenderNormalizer().normalise(report, context))

    emitted = {event["tartarus"]["defender"]["detection_id"] for event in events}
    assert emitted == {threat["detection_id"] for threat in verdict["threats"]}
