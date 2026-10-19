from datetime import datetime
from pathlib import Path
from typing import Any

from app.ingest import ecs
from app.ingest.defender import DefenderNormalizer
from tests.ingest.contract import check_normalizer_contract
from tests.ingest.defender_cases import (
    ANALYSIS_ID,
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


def normalise(
    root: Path, report: dict[str, Any], started: datetime = EICAR_STARTED
) -> tuple[list[dict[str, Any]], DefenderNormalizer]:
    normalizer = DefenderNormalizer()
    events = list(normalizer.normalise(report, context_of(root, started)))
    return events, normalizer


def eicar_events(tmp_path: Path) -> tuple[list[dict[str, Any]], DefenderNormalizer]:
    root = copy_export(tmp_path, "defender-eicar-sample.xml")
    return normalise(root, report_of(EICAR_TASK, EICAR_STARTED))


def dropped_events(tmp_path: Path) -> tuple[list[dict[str, Any]], DefenderNormalizer]:
    root = copy_export(tmp_path, "defender-dropped-file.xml")
    return normalise(
        root, report_of(DROPPED_TASK, DROPPED_STARTED, (DROPPER_IMAGE,)), DROPPED_STARTED
    )


def test_eicar_run_yields_the_sample_detection_and_its_quarantine_only(tmp_path: Path) -> None:
    events, normalizer = eicar_events(tmp_path)

    assert [event["event"]["action"] for event in events] == [
        "malware-detected",
        "malware-quarantined",
    ]
    assert normalizer.ignored_tooling_detections == 1


def test_detection_is_an_alert_with_the_threat_as_its_rule(tmp_path: Path) -> None:
    detection = eicar_events(tmp_path)[0][0]

    assert detection["event"]["kind"] == "alert"
    assert detection["event"]["module"] == "defender"
    assert detection["event"]["dataset"] == "defender.operational"
    assert detection["event"]["category"] == ["malware", "file"]
    assert detection["event"]["type"] == ["info", "indicator"]
    assert detection["event"]["severity"] == 4
    assert detection["tartarus"]["lane"] == "file"
    assert detection["rule"] == {
        "id": "2147519003",
        "name": "Virus:DOS/EICAR_Test_File",
        "ruleset": "defender",
        "description": "Wirus",
        "reference": [
            "https://go.microsoft.com/fwlink/?linkid=37020&name=Virus:DOS/EICAR_Test_File"
            "&threatid=2147519003&enterprise=0"
        ],
    }


def test_detection_names_the_sample_file_and_no_process(tmp_path: Path) -> None:
    detection = eicar_events(tmp_path)[0][0]

    assert detection["file"] == {
        "path": EICAR_SAMPLE_PATH,
        "name": "eicar.com",
        "extension": "com",
    }
    assert "process" not in detection
    assert detection["tartarus"]["defender"]["scope"] == "sample"
    assert detection["tartarus"]["detection"]["match"].startswith("path: ")


def test_quarantine_is_an_event_that_links_to_its_detection(tmp_path: Path) -> None:
    detection, quarantine = eicar_events(tmp_path)[0]

    assert quarantine["event"]["kind"] == "event"
    assert quarantine["event"]["action"] == "malware-quarantined"
    assert quarantine["event"]["type"] == ["deletion"]
    assert quarantine["event"]["outcome"] == "success"
    assert quarantine["event"]["severity"] == 0
    assert quarantine["rule"] == {
        "id": "2147519003",
        "name": "Virus:DOS/EICAR_Test_File",
        "ruleset": "defender",
    }
    assert quarantine["user"] == {"name": "SYSTEM", "domain": "ZARZĄDZANIE NT"}
    assert quarantine["related"] == {"events": [detection["event"]["id"]]}


def test_timestamps_are_the_guest_clock_calibrated_and_clamped_to_the_run(tmp_path: Path) -> None:
    detection, quarantine = eicar_events(tmp_path)[0]

    assert detection["@timestamp"] == "2026-10-18T23:33:45.000Z"
    assert detection["tartarus"]["defender"]["clock"] == "snapshot"
    assert quarantine["@timestamp"] == "2026-10-18T23:33:59.121Z"
    assert "clock" not in quarantine["tartarus"]["defender"]


def test_dropped_file_names_the_process_that_wrote_it(tmp_path: Path) -> None:
    events, normalizer = dropped_events(tmp_path)
    dropped = next(event for event in events if event["event"]["action"] == "malware-detected")

    assert dropped["file"]["path"] == r"C:\Users\Public\tt-dropped-eicar.txt"
    assert dropped["process"] == {
        "executable": DROPPER_IMAGE,
        "name": "dropper.exe",
    }
    assert dropped["tartarus"]["defender"]["scope"] == "dropped"
    assert dropped["event"]["severity"] == 4
    assert normalizer.ignored_tooling_detections == 1


def test_dropped_file_timestamp_is_the_run_clock_not_clamped(tmp_path: Path) -> None:
    events, _ = dropped_events(tmp_path)
    dropped = next(event for event in events if event["event"]["action"] == "malware-detected")

    assert dropped["@timestamp"] == "2026-10-18T23:26:21.431Z"
    assert "clock" not in dropped["tartarus"]["defender"]


def test_benign_tooling_only_yields_nothing_and_counts_the_tooling_detection(
    tmp_path: Path,
) -> None:
    root = copy_export(tmp_path, "defender-benign-tooling-only.xml")

    events, normalizer = normalise(root, report_of(EICAR_TASK, EICAR_STARTED))

    assert events == []
    assert normalizer.ignored_tooling_detections == 1


def test_clean_guest_baseline_drops_config_and_update_noise(tmp_path: Path) -> None:
    root = copy_export(tmp_path, "defender-clean-guest-baseline.xml")

    events, _ = normalise(root, report_of(EICAR_TASK, EICAR_STARTED))

    assert events == []


def test_defender_off_export_yields_nothing(tmp_path: Path) -> None:
    root = copy_export(tmp_path, "defender-off-guest.xml")

    events, _ = normalise(root, report_of(EICAR_TASK, EICAR_STARTED))

    assert events == []


def test_empty_export_file_yields_nothing(tmp_path: Path) -> None:
    root = write_export(tmp_path, "")

    events, _ = normalise(root, report_of(EICAR_TASK, EICAR_STARTED))

    assert events == []


def test_missing_export_or_no_analysis_folder_yields_nothing(tmp_path: Path) -> None:
    report = report_of(EICAR_TASK, EICAR_STARTED)

    assert list(DefenderNormalizer().normalise(report, context_of(None))) == []
    assert list(DefenderNormalizer().normalise(report, context_of(tmp_path))) == []


def test_detection_without_a_closing_event_links_nothing_and_stays_a_detection(
    tmp_path: Path,
) -> None:
    detected = event_xml(1116, 300, "2026-10-18T21:09:44.8Z", detection_data())
    root = write_export(tmp_path, export_xml(detected))

    events, _ = normalise(root, report_of(EICAR_TASK, EICAR_STARTED))

    assert [event["event"]["action"] for event in events] == ["malware-detected"]
    assert "related" not in events[0]


def test_unknown_action_id_is_kept_as_an_action_taken_event(tmp_path: Path) -> None:
    detected = event_xml(1116, 300, "2026-10-18T21:09:44.8Z", detection_data())
    unknown = event_xml(1117, 301, "2026-10-18T21:09:50.8Z", closing_data(action_id="7"))
    root = write_export(tmp_path, export_xml(detected, unknown))

    events, _ = normalise(root, report_of(EICAR_TASK, EICAR_STARTED))

    action_taken = events[1]
    assert action_taken["event"]["action"] == "malware-action-taken"
    assert action_taken["event"]["type"] == ["info"]
    assert action_taken["event"]["outcome"] == "success"
    assert action_taken["related"] == {"events": [events[0]["event"]["id"]]}


def test_closing_event_without_its_detection_is_kept_and_links_nothing(tmp_path: Path) -> None:
    orphan = event_xml(
        1117, 302, "2026-10-18T21:09:50.8Z", closing_data("{00000000-0000-0000-0000-000000000001}")
    )
    root = write_export(tmp_path, export_xml(orphan))

    events, _ = normalise(root, report_of(EICAR_TASK, EICAR_STARTED))

    assert [event["event"]["action"] for event in events] == ["malware-quarantined"]
    assert "related" not in events[0]


def test_failed_action_is_an_event_with_failure_outcome(tmp_path: Path) -> None:
    detected = event_xml(1116, 300, "2026-10-18T21:09:44.8Z", detection_data())
    failed_data = closing_data(action_id="2") | {
        "Error Code": "0x80070002",
        "Error Description": "Nie znaleziono pliku.",
    }
    failed = event_xml(1118, 301, "2026-10-18T21:09:50.8Z", failed_data)
    root = write_export(tmp_path, export_xml(detected, failed))

    events, _ = normalise(root, report_of(EICAR_TASK, EICAR_STARTED))

    failure = events[1]
    assert failure["event"]["action"] == "malware-action-failed"
    assert failure["event"]["outcome"] == "failure"
    assert failure["event"]["severity"] == 3
    assert failure["error"] == {"code": "0x80070002", "message": "Nie znaleziono pliku."}
    assert failure["related"] == {"events": [events[0]["event"]["id"]]}


def test_non_ascii_dropped_path_is_kept_as_written(tmp_path: Path) -> None:
    path = r"C:\Users\Public\zażółć-тест-测试.txt"
    detected = event_xml(
        1116, 300, "2026-10-18T23:26:21.4Z", detection_data(path=path, process=DROPPER_IMAGE)
    )
    root = write_export(tmp_path, export_xml(detected))

    events, _ = normalise(
        root, report_of(DROPPED_TASK, DROPPED_STARTED, (DROPPER_IMAGE,)), DROPPED_STARTED
    )

    assert events[0]["file"]["path"] == path
    assert events[0]["file"]["name"] == "zażółć-тест-测试.txt"


def test_the_sample_detection_event_id_is_what_the_quarantine_points_to(tmp_path: Path) -> None:
    events, _ = eicar_events(tmp_path)
    expected = ecs.event_id(ANALYSIS_ID, "defender", "defender", 275)

    assert events[0]["event"]["id"] == expected
    assert events[1]["related"]["events"] == [expected]


def test_every_emitted_event_keeps_the_common_contract(tmp_path: Path) -> None:
    root = copy_export(tmp_path, "defender-dropped-file.xml")
    check_normalizer_contract(
        DefenderNormalizer(),
        report_of(DROPPED_TASK, DROPPED_STARTED, (DROPPER_IMAGE,)),
        context_of(root, DROPPED_STARTED),
    )


def test_detection_ids_are_the_guest_detection_guids(tmp_path: Path) -> None:
    events, _ = eicar_events(tmp_path)

    assert {event["tartarus"]["defender"]["detection_id"] for event in events} == {EICAR_DETECTION}
