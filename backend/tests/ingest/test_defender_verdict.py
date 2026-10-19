from pathlib import Path
from typing import Any

from app.analyses.defender import DefenderStatus, DefenderThreat, DefenderVerdict
from app.ingest.defender import DefenderNormalizer
from app.ingest.defender_export import Outcome, Scope
from app.ingest.defender_verdict import (
    collapse_repeated_threats,
    defender_verdict,
    verdict_of_export,
)
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
    verdict = defender_verdict(report, context_of(root, EICAR_STARTED), process_count)
    return verdict.model_dump(mode="json")


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

    verdict = defender_verdict(
        report, context_of(root, DROPPED_STARTED), process_count=1
    ).model_dump(mode="json")

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

    verdict = defender_verdict(report, context, process_count=1).model_dump(mode="json")
    events = list(DefenderNormalizer().normalise(report, context))

    emitted = {event["tartarus"]["defender"]["detection_id"] for event in events}
    assert emitted == {threat["detection_id"] for threat in verdict["threats"]}


def test_the_verdict_is_a_typed_model(tmp_path: Path) -> None:
    root = copy_export(tmp_path, "defender-eicar-sample.xml")
    report = report_of(EICAR_TASK, EICAR_STARTED)

    verdict = defender_verdict(report, context_of(root, EICAR_STARTED), process_count=0)

    assert isinstance(verdict, DefenderVerdict)
    assert verdict.status is DefenderStatus.REMOVED
    assert verdict.threats[0].detection_id == EICAR_DETECTION


def test_no_export_is_a_verdict_of_its_own(tmp_path: Path) -> None:
    report = report_of(EICAR_TASK, EICAR_STARTED)

    verdict = defender_verdict(report, context_of(tmp_path, EICAR_STARTED), process_count=0)

    assert verdict == DefenderVerdict(
        status=DefenderStatus.NO_EXPORT, sample_removed=False, blocked_before_run=False, threats=[]
    )


def test_the_normaliser_keeps_the_export_it_read_so_the_verdict_needs_no_second_read(
    tmp_path: Path,
) -> None:
    root = copy_export(tmp_path, "defender-eicar-sample.xml")
    report = report_of(EICAR_TASK, EICAR_STARTED)
    context = context_of(root, EICAR_STARTED)
    normalizer = DefenderNormalizer()
    assert normalizer.export is None

    list(normalizer.normalise(report, context))

    assert verdict_of_export(normalizer.export, process_count=0) == defender_verdict(
        report, context, process_count=0
    )


SECOND_DETECTION = "{9B4BFAF1-6D6D-406E-AADE-06C5B6A9E568}"
OTHER_EICAR_PATH = r"C:\Users\Alice\AppData\Local\Temp\321\other.com"


def detected(
    record_id: int,
    guest_time: str,
    detection_id: str = EICAR_DETECTION,
    path: str = EICAR_SAMPLE_PATH,
    threat_id: str = "2147519003",
) -> str:
    data = detection_data(path=path, detection_id=detection_id, threat_id=threat_id)
    return event_xml(1116, record_id, guest_time, data)


def removed(record_id: int, guest_time: str, detection_id: str = EICAR_DETECTION) -> str:
    return event_xml(1117, record_id, guest_time, closing_data(detection_id=detection_id))


def failed(record_id: int, guest_time: str, detection_id: str = EICAR_DETECTION) -> str:
    return event_xml(1119, record_id, guest_time, closing_data(detection_id=detection_id))


def threat(**fields: object) -> DefenderThreat:
    base: dict[str, object] = {
        "detection_id": EICAR_DETECTION,
        "threat_id": 2147519003,
        "name": "Virus:DOS/EICAR_Test_File",
        "severity": 4,
        "category_id": 42,
        "scope": Scope.SAMPLE,
        "path": EICAR_SAMPLE_PATH,
        "process": r"C:\Python311\pythonw.exe",
        "user": "DESKTOP-2YK5XLK\\Alice",
        "detected_at": "2026-10-18T23:34:00.000Z",
        "action": "quarantine",
        "outcome": Outcome.REMOVED,
        "removed_at": "2026-10-18T23:34:01.000Z",
    }
    return DefenderThreat(**(base | fields))  # type: ignore[arg-type]


def test_two_detections_of_one_file_are_one_threat(tmp_path: Path) -> None:
    root = write_export(
        tmp_path,
        export_xml(
            detected(300, "2026-10-18T21:34:00.000Z"),
            removed(301, "2026-10-18T21:34:01.000Z"),
            detected(302, "2026-10-18T21:34:15.000Z", detection_id=SECOND_DETECTION),
            removed(303, "2026-10-18T21:34:16.000Z", detection_id=SECOND_DETECTION),
        ),
    )

    verdict = verdict_of(root, process_count=0)

    assert verdict["status"] == "removed"
    assert verdict["sample_removed"] is True
    assert verdict["blocked_before_run"] is True
    assert len(verdict["threats"]) == 1
    assert verdict["threats"][0]["detection_id"] == EICAR_DETECTION
    assert verdict["threats"][0]["detected_at"] == "2026-10-18T23:34:00.000Z"
    assert verdict["threats"][0]["removed_at"] == "2026-10-18T23:34:16.000Z"
    assert verdict["threats"][0]["outcome"] == "removed"


def test_the_events_still_record_each_detection(tmp_path: Path) -> None:
    root = write_export(
        tmp_path,
        export_xml(
            detected(300, "2026-10-18T21:34:00.000Z"),
            removed(301, "2026-10-18T21:34:01.000Z"),
            detected(302, "2026-10-18T21:34:15.000Z", detection_id=SECOND_DETECTION),
            removed(303, "2026-10-18T21:34:16.000Z", detection_id=SECOND_DETECTION),
        ),
    )
    report = report_of(EICAR_TASK, EICAR_STARTED)

    events = list(DefenderNormalizer().normalise(report, context_of(root, EICAR_STARTED)))

    assert {event["tartarus"]["defender"]["detection_id"] for event in events} == {
        EICAR_DETECTION,
        SECOND_DETECTION,
    }


def test_a_repeat_at_another_path_is_its_own_threat(tmp_path: Path) -> None:
    root = write_export(
        tmp_path,
        export_xml(
            detected(300, "2026-10-18T21:34:00.000Z"),
            removed(301, "2026-10-18T21:34:01.000Z"),
            detected(
                302,
                "2026-10-18T21:34:15.000Z",
                detection_id=SECOND_DETECTION,
                path=OTHER_EICAR_PATH,
            ),
            removed(303, "2026-10-18T21:34:16.000Z", detection_id=SECOND_DETECTION),
        ),
    )

    verdict = verdict_of(root, process_count=0)

    assert [entry["path"] for entry in verdict["threats"]] == [EICAR_SAMPLE_PATH, OTHER_EICAR_PATH]


def test_a_failed_repeat_makes_the_one_threat_failed(tmp_path: Path) -> None:
    root = write_export(
        tmp_path,
        export_xml(
            detected(300, "2026-10-18T21:34:00.000Z"),
            removed(301, "2026-10-18T21:34:01.000Z"),
            detected(302, "2026-10-18T21:34:15.000Z", detection_id=SECOND_DETECTION),
            failed(303, "2026-10-18T21:34:16.000Z", detection_id=SECOND_DETECTION),
        ),
    )

    verdict = verdict_of(root, process_count=0)

    assert verdict["status"] == "failed"
    assert verdict["sample_removed"] is False
    assert len(verdict["threats"]) == 1
    assert verdict["threats"][0]["outcome"] == "failed"


def test_a_removed_repeat_beside_a_pending_one_is_removed(tmp_path: Path) -> None:
    root = write_export(
        tmp_path,
        export_xml(
            detected(300, "2026-10-18T21:34:00.000Z"),
            removed(301, "2026-10-18T21:34:01.000Z"),
            detected(302, "2026-10-18T21:34:15.000Z", detection_id=SECOND_DETECTION),
        ),
    )

    verdict = verdict_of(root, process_count=0)

    assert verdict["status"] == "removed"
    assert verdict["sample_removed"] is True
    assert len(verdict["threats"]) == 1
    assert verdict["threats"][0]["outcome"] == "removed"
    assert verdict["threats"][0]["action"] == "quarantine"
    assert verdict["threats"][0]["removed_at"] == "2026-10-18T23:34:01.000Z"


def test_repeats_without_a_threat_id_are_one_threat_by_name(tmp_path: Path) -> None:
    root = write_export(
        tmp_path,
        export_xml(
            detected(300, "2026-10-18T21:34:00.000Z", threat_id=""),
            removed(301, "2026-10-18T21:34:01.000Z"),
            detected(302, "2026-10-18T21:34:15.000Z", detection_id=SECOND_DETECTION, threat_id=""),
            removed(303, "2026-10-18T21:34:16.000Z", detection_id=SECOND_DETECTION),
        ),
    )

    verdict = verdict_of(root, process_count=0)

    assert len(verdict["threats"]) == 1


def test_collapse_keeps_different_scopes_apart() -> None:
    sample = threat(scope=Scope.SAMPLE)
    dropped = threat(scope=Scope.DROPPED, detection_id=SECOND_DETECTION)

    assert collapse_repeated_threats([sample, dropped]) == [sample, dropped]


def test_collapse_keeps_different_names_apart_when_there_is_no_threat_id() -> None:
    eicar = threat(threat_id=None, name="Virus:DOS/EICAR_Test_File")
    other = threat(threat_id=None, name="Trojan:Win32/Other", detection_id=SECOND_DETECTION)

    assert collapse_repeated_threats([eicar, other]) == [eicar, other]


def test_collapse_matches_paths_case_insensitively() -> None:
    upper = threat(path=EICAR_SAMPLE_PATH.upper(), detection_id=SECOND_DETECTION)
    lower = threat(path=EICAR_SAMPLE_PATH.lower())

    assert len(collapse_repeated_threats([lower, upper])) == 1
