from collections import Counter
from pathlib import Path
from typing import Any, NamedTuple

import pytest

from app.ingest.sysmon import SysmonNormalizer
from tests.ingest.sysmon_cases import (
    AGENT,
    ANALYZER_DIR,
    BENIGN,
    CMD,
    SVCHOST,
    analysis_with,
    analysis_with_fixture,
    context_of,
    event_xml,
    guid,
    monitored,
    report_with,
)

SAMPLE_PID = 500
SAMPLE = guid(1)
AGENT_PID = 400
AGENT_GUID = guid(2)
INJECTOR = f"{ANALYZER_DIR}\\bin\\ySwqZiza.exe"
TIME = "2026-10-18 20:43:50.000"
NOTEPAD = "C:\\Windows\\System32\\notepad.exe"
WEVTUTIL = "C:\\Windows\\System32\\wevtutil.exe"

TOOLING = "cape-tooling"
BACKGROUND = "windows-background"
MONITOR_ARTEFACT = "monitor-artefact"


def sysmon(event_id: int, record_id: int, **data: str | int) -> str:
    return event_xml(event_id, record_id, TIME, {"UtcTime": TIME, **data})


class Proc(NamedTuple):
    pid: int
    image: str
    guid: int


def process_started(record_id: int, child: Proc, parent: Proc) -> str:
    return sysmon(
        1,
        record_id,
        ProcessGuid=guid(child.guid),
        ProcessId=child.pid,
        Image=child.image,
        CommandLine=child.image,
        ParentProcessGuid=guid(parent.guid),
        ParentProcessId=parent.pid,
        ParentImage=parent.image,
        ParentCommandLine=parent.image,
    )


def file_created(record_id: int, pid: int, image: str, path: str, *, own: int | None) -> str:
    fields: dict[str, str | int] = {"ProcessId": pid, "Image": image, "TargetFilename": path}
    if own is not None:
        fields["ProcessGuid"] = guid(own)
    return sysmon(11, record_id, **fields)


def image_loaded(record_id: int, pid: int, image: str, loaded: str, *, own: int) -> str:
    return sysmon(
        7, record_id, ProcessGuid=guid(own), ProcessId=pid, Image=image, ImageLoaded=loaded
    )


def process_event(
    event_id: int,
    record_id: int,
    source: tuple[int, int, str],
    target: tuple[int, int, str],
) -> str:
    (source_pid, source_guid, source_image) = source
    (target_pid, target_guid, target_image) = target
    return sysmon(
        event_id,
        record_id,
        SourceProcessGUID=guid(source_guid),
        SourceProcessId=source_pid,
        SourceImage=source_image,
        TargetProcessGUID=guid(target_guid),
        TargetProcessId=target_pid,
        TargetImage=target_image,
        GrantedAccess="0x1fffff",
    )


SAMPLE_STARTED = process_started(1, Proc(SAMPLE_PID, BENIGN, 1), Proc(AGENT_PID, AGENT, 2))


def run(
    tmp_path: Path, *events: str, processes: tuple[dict[str, Any], ...] | None = None
) -> tuple[set[int], Counter[str]]:
    """The record ids that survive, and what was dropped by reason."""
    report = report_with(
        *(processes if processes is not None else (monitored(SAMPLE_PID, BENIGN),))
    )
    normalizer = SysmonNormalizer()
    root = analysis_with(tmp_path, SAMPLE_STARTED, *events)
    kept = {
        event["tartarus"]["raw"]["EventRecordID"]
        for event in normalizer.normalise(report, context_of(root))
    }
    return kept - {1}, normalizer.dropped


# --- the process tree ----------------------------------------------------------------------


def test_the_sample_and_its_descendants_are_kept(tmp_path: Path) -> None:
    kept, dropped = run(
        tmp_path,
        process_started(10, Proc(501, CMD, 3), Proc(SAMPLE_PID, BENIGN, 1)),
        file_created(11, 501, CMD, "C:\\Users\\Megan\\a.txt", own=3),
        process_started(12, Proc(502, NOTEPAD, 4), Proc(501, CMD, 3)),
        file_created(13, 502, NOTEPAD, "C:\\Users\\Megan\\b.txt", own=4),
    )

    assert kept == {10, 11, 12, 13}
    assert not dropped


def test_a_child_is_kept_through_its_parent_guid_even_when_the_report_lacks_it(
    tmp_path: Path,
) -> None:
    kept, _ = run(
        tmp_path,
        process_started(10, Proc(777, CMD, 3), Proc(SAMPLE_PID, BENIGN, 1)),
        file_created(11, 777, CMD, "C:\\x.txt", own=3),
    )

    assert kept == {10, 11}


def test_a_child_of_a_sample_process_whose_start_is_not_logged_is_kept_by_pid(
    tmp_path: Path,
) -> None:
    child = process_started(10, Proc(777, CMD, 3), Proc(4242, "C:\\Temp\\other.exe", 42))
    kept, _ = run(
        tmp_path,
        child,
        file_created(11, 777, CMD, "C:\\x.txt", own=3),
        processes=(monitored(SAMPLE_PID, BENIGN), monitored(4242, "C:\\Temp\\other.exe")),
    )

    assert kept == {10, 11}


def test_an_unrelated_process_is_background(tmp_path: Path) -> None:
    kept, dropped = run(
        tmp_path,
        process_started(
            10, Proc(900, SVCHOST, 5), Proc(4, "C:\\Windows\\System32\\services.exe", 6)
        ),
        file_created(11, 900, SVCHOST, "C:\\Windows\\Temp\\x.tmp", own=5),
    )

    assert kept == set()
    assert dropped == {BACKGROUND: 2}


def test_a_known_process_that_reuses_a_sample_pid_is_background(tmp_path: Path) -> None:
    kept, dropped = run(
        tmp_path,
        process_started(10, Proc(SAMPLE_PID, NOTEPAD, 6), Proc(4, "C:\\Windows\\explorer.exe", 7)),
        file_created(11, SAMPLE_PID, NOTEPAD, "C:\\Windows\\Temp\\y.tmp", own=6),
    )

    assert kept == set()
    assert dropped == {BACKGROUND: 2}


def test_an_unknown_process_with_a_sample_pid_is_kept_whatever_its_image(tmp_path: Path) -> None:
    kept, dropped = run(
        tmp_path,
        file_created(10, SAMPLE_PID, BENIGN, "C:\\x.txt", own=70),
        file_created(11, SAMPLE_PID, NOTEPAD, "C:\\y.txt", own=71),
    )

    assert kept == {10, 11}
    assert not dropped


def test_an_unknown_process_with_another_pid_is_background(tmp_path: Path) -> None:
    kept, dropped = run(tmp_path, file_created(10, 9999, SVCHOST, "C:\\x.txt", own=70))

    assert kept == set()
    assert dropped == {BACKGROUND: 1}


def test_an_event_that_names_no_process_is_kept(tmp_path: Path) -> None:
    kept, _ = run(tmp_path, sysmon(11, 10, Image=SVCHOST, TargetFilename="C:\\x.txt"))

    assert kept == {10}


def test_a_report_without_processes_has_no_background_to_tell(tmp_path: Path) -> None:
    kept, dropped = run(
        tmp_path,
        file_created(10, 9999, SVCHOST, "C:\\x.txt", own=70),
        file_created(11, AGENT_PID, AGENT, "C:\\y.txt", own=2),
        processes=(),
    )

    assert kept == {10}
    assert dropped == {TOOLING: 1}


def test_wmi_events_name_no_process_and_are_kept(tmp_path: Path) -> None:
    kept, _ = run(
        tmp_path,
        sysmon(
            19, 10, Operation="Created", Name="f", Query="SELECT 1", EventNamespace="root\\cimv2"
        ),
        sysmon(20, 11, Operation="Created", Name="c", Type="Command Line", Destination="x"),
        sysmon(21, 12, Operation="Created", Consumer="c", Filter="f"),
    )

    assert kept == {10, 11, 12}


# --- CAPE's own tooling --------------------------------------------------------------------


def test_the_agent_and_its_children_are_tooling(tmp_path: Path) -> None:
    kept, dropped = run(
        tmp_path,
        sysmon(
            3,
            10,
            ProcessGuid=AGENT_GUID,
            ProcessId=AGENT_PID,
            Image=AGENT,
            Protocol="tcp",
            Initiated="false",
            SourceIp="192.168.150.1",
            SourcePort=50000,
            DestinationIp="192.168.150.14",
            DestinationPort=8000,
        ),
        process_started(11, Proc(601, WEVTUTIL, 8), Proc(AGENT_PID, AGENT, 2)),
        file_created(12, 601, WEVTUTIL, "C:\\Windows\\Temp\\export.xml", own=8),
        process_started(13, Proc(602, CMD, 9), Proc(AGENT_PID, AGENT, 2)),
    )

    assert kept == set()
    assert dropped == {TOOLING: 4}


def test_the_injector_and_the_ppl_injector_are_tooling_wherever_they_are_renamed_to(
    tmp_path: Path,
) -> None:
    kept, dropped = run(
        tmp_path,
        process_started(10, Proc(610, INJECTOR, 8), Proc(AGENT_PID, AGENT, 2)),
        image_loaded(11, 610, INJECTOR, INJECTOR, own=8),
        file_created(12, 611, f"{ANALYZER_DIR}\\bin\\PPLinject64.exe", "C:\\611.ini", own=None),
        file_created(13, 612, "C:\\Windows\\SMaster64.exe", "C:\\x", own=None),
        file_created(14, 613, "C:\\Windows\\Sysmon64.exe", "C:\\x", own=None),
    )

    assert kept == set()
    assert dropped == {TOOLING: 5}


def test_the_injector_acting_on_the_sample_is_tooling_not_a_remote_thread(tmp_path: Path) -> None:
    injector = (610, 8, INJECTOR)
    kept, dropped = run(
        tmp_path,
        process_event(8, 10, injector, (SAMPLE_PID, 1, BENIGN)),
        process_event(10, 11, injector, (SAMPLE_PID, 1, BENIGN)),
    )

    assert kept == set()
    assert dropped == {TOOLING: 2}


def test_another_process_acting_on_the_sample_is_kept(tmp_path: Path) -> None:
    stranger = (9999, 9, SVCHOST)
    kept, _ = run(
        tmp_path,
        process_event(10, 10, stranger, (SAMPLE_PID, 1, BENIGN)),
        process_event(8, 11, stranger, (SAMPLE_PID, 1, BENIGN)),
        process_event(10, 12, stranger, (9998, 5, SVCHOST)),
    )

    assert kept == {10, 11}


def test_the_sample_acting_on_anything_is_kept(tmp_path: Path) -> None:
    kept, _ = run(tmp_path, process_event(8, 10, (SAMPLE_PID, 1, BENIGN), (9998, 5, SVCHOST)))

    assert kept == {10}


def test_a_guid_spelled_in_capitals_still_names_the_process(tmp_path: Path) -> None:
    # EID 10 writes `SourceProcessGUID`; the child's pid is not the report's, only its guid
    # links it to the sample.
    kept, dropped = run(
        tmp_path,
        process_started(10, Proc(777, CMD, 3), Proc(SAMPLE_PID, BENIGN, 1)),
        process_event(10, 11, (777, 3, CMD), (9998, 5, SVCHOST)),
    )

    assert kept == {10, 11}
    assert not dropped


def test_what_the_sample_itself_runs_is_kept_even_when_it_looks_like_tooling(
    tmp_path: Path,
) -> None:
    kept, dropped = run(
        tmp_path,
        process_started(10, Proc(620, WEVTUTIL, 8), Proc(SAMPLE_PID, BENIGN, 1)),
        file_created(11, 620, WEVTUTIL, "C:\\Windows\\Temp\\evidence.xml", own=8),
    )

    assert kept == {10, 11}
    assert not dropped


def test_the_monitors_own_files_in_a_sample_process_are_artefacts(tmp_path: Path) -> None:
    kept, dropped = run(
        tmp_path,
        file_created(10, SAMPLE_PID, BENIGN, f"{ANALYZER_DIR}\\CAPE\\CapeOutput.bin", own=1),
        file_created(11, SAMPLE_PID, BENIGN, f"{ANALYZER_DIR}\\data\\yara\\capemon.yac", own=1),
        file_created(12, SAMPLE_PID, BENIGN, f"C:\\{SAMPLE_PID}.ini", own=1),
        file_created(13, SAMPLE_PID, BENIGN, f"{ANALYZER_DIR}\\dll\\{SAMPLE_PID}.ini", own=1),
        image_loaded(14, SAMPLE_PID, BENIGN, f"{ANALYZER_DIR}\\dll\\HHvmrlWh.dll", own=1),
    )

    assert kept == set()
    assert dropped == {MONITOR_ARTEFACT: 5}


@pytest.mark.parametrize("root", [r"C:\VTroer", r"C:\ShgRuKILV", r"C:\abcdefghij"])
def test_the_monitors_results_folder_is_an_artefact_whatever_its_random_length(
    tmp_path: Path, root: str
) -> None:
    # The analyzer's results folder is 6 to 10 random characters (CAPE's constants.py), unlike the
    # 8-character folder it is unpacked into; the real run's folders were 6 and 9 long, and the
    # folder itself is created without a trailing separator.
    kept, dropped = run(
        tmp_path,
        file_created(10, SAMPLE_PID, BENIGN, f"{root}\\CAPE", own=1),
        file_created(11, SAMPLE_PID, BENIGN, f"{root}\\CAPE\\CapeOutput.bin", own=1),
    )

    assert kept == set()
    assert dropped == {MONITOR_ARTEFACT: 2}


def test_a_sample_file_with_an_unlucky_name_is_not_an_artefact(tmp_path: Path) -> None:
    kept, dropped = run(
        tmp_path,
        file_created(10, SAMPLE_PID, BENIGN, "C:\\abcdefgh\\payload.exe", own=1),
        file_created(11, SAMPLE_PID, BENIGN, "C:\\Users\\Megan\\settings.ini", own=1),
        file_created(12, SAMPLE_PID, BENIGN, "C:\\ProgramData\\123.ini", own=1),
        image_loaded(13, SAMPLE_PID, BENIGN, "C:\\Windows\\System32\\ntdll.dll", own=1),
    )

    assert kept == {10, 11, 12, 13}
    assert not dropped


def test_events_of_sysmon_itself_are_counted_apart_from_noise(tmp_path: Path) -> None:
    kept, dropped = run(tmp_path, sysmon(16, 10, Configuration="x"), sysmon(4, 11, State="Started"))

    assert kept == set()
    assert dropped == {"sysmon-service": 2}


# --- the real fixture -----------------------------------------------------------------------


def fixture_run(
    tmp_path: Path, *processes: dict[str, Any]
) -> tuple[list[dict[str, Any]], Counter[str]]:
    normalizer = SysmonNormalizer()
    root = analysis_with_fixture(tmp_path)
    events = list(normalizer.normalise(report_with(*processes), context_of(root)))
    return events, normalizer.dropped


def test_in_the_fixture_the_sample_keeps_its_dns_query_and_image_load_only(tmp_path: Path) -> None:
    events, dropped = fixture_run(tmp_path, monitored(8364, BENIGN), monitored(1512, CMD))

    assert [event["tartarus"]["raw"]["EventRecordID"] for event in events] == [365, 533]
    assert dropped == {TOOLING: 75, MONITOR_ARTEFACT: 2, BACKGROUND: 208}
    assert len(events) + sum(dropped.values()) == 287


def test_in_the_fixture_every_event_of_the_injector_is_tooling(tmp_path: Path) -> None:
    events, dropped = fixture_run(tmp_path, monitored(8364, BENIGN))

    assert not [e for e in events if "ySwqZiza" in str(e["tartarus"]["raw"])]
    assert dropped[TOOLING] == 75


def test_in_the_fixture_with_no_sample_only_tooling_is_dropped(tmp_path: Path) -> None:
    events, dropped = fixture_run(tmp_path)

    assert dropped == {TOOLING: 75}
    assert len(events) == 212
