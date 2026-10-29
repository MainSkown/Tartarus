import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from app.ingest.capemon import CapemonNormalizer
from app.ingest.protocol import IngestContext
from app.ingest.sysmon import SysmonNormalizer
from tests.ingest.contract import check_normalizer_contract
from tests.ingest.reports import call
from tests.ingest.sysmon_cases import (
    BENIGN,
    CMD,
    SHELL_HOST,
    WIDE_REPORT,
    analysis_with,
    analysis_with_fixture,
    context_of,
    event_xml,
    guid,
    monitored,
    report_with,
)

Event = dict[str, Any]


def normalise(report: dict[str, Any], context: IngestContext) -> list[Event]:
    return list(SysmonNormalizer().normalise(report, context))


def by_record(events: list[Event]) -> dict[int, Event]:
    return {event["tartarus"]["raw"]["EventRecordID"]: event for event in events}


@pytest.fixture(scope="module")
def fixture_events(tmp_path_factory: pytest.TempPathFactory) -> dict[int, Event]:
    root = analysis_with_fixture(tmp_path_factory.mktemp("analysis"))
    return by_record(normalise(WIDE_REPORT, context_of(root)))


def hand_written(tmp_path: Path, *events: str, report: dict[str, Any] | None = None) -> list[Event]:
    root = analysis_with(tmp_path, *events)
    return normalise(report or report_with(monitored(500, BENIGN)), context_of(root))


def only(events: list[Event]) -> Event:
    assert len(events) == 1, [event["event"]["action"] for event in events]
    return events[0]


# --- input ---------------------------------------------------------------------------------


def test_source_is_sysmon() -> None:
    assert SysmonNormalizer().source == "sysmon"


def test_no_analysis_folder_means_no_events() -> None:
    assert normalise(WIDE_REPORT, context_of(None)) == []


def test_a_folder_without_the_export_means_no_events(tmp_path: Path) -> None:
    assert normalise(WIDE_REPORT, context_of(tmp_path)) == []


def test_a_garbage_export_means_no_events_and_no_error(tmp_path: Path) -> None:
    (tmp_path / "sysmon").mkdir()
    (tmp_path / "sysmon" / "sysmon.xml").write_bytes(b"\x00\xff not xml at all")

    assert normalise(WIDE_REPORT, context_of(tmp_path)) == []


def test_normalise_is_lazy(tmp_path: Path) -> None:
    result = SysmonNormalizer().normalise(WIDE_REPORT, context_of(analysis_with_fixture(tmp_path)))

    assert isinstance(result, Iterator)
    assert not isinstance(result, list)


def test_the_report_is_not_read_for_sysmon_events(tmp_path: Path) -> None:
    report = {**WIDE_REPORT, "sysmon": [{"System": {"EventID": "1"}}]}
    root = analysis_with_fixture(tmp_path)

    assert normalise(report, context_of(root)) == normalise(WIDE_REPORT, context_of(root))


# --- the real fixture, one test per mapped event id ----------------------------------------


def test_every_event_is_a_sysmon_event(fixture_events: dict[int, Event]) -> None:
    assert {event["event"]["module"] for event in fixture_events.values()} == {"sysmon"}
    assert {event["event"]["dataset"] for event in fixture_events.values()} == {"sysmon.evtx"}
    assert {event["tartarus"]["phase"] for event in fixture_events.values()} == {"final"}


def test_eid_1_process_created(fixture_events: dict[int, Event]) -> None:
    event = fixture_events[2667]

    assert event["@timestamp"] == "2026-10-18T22:46:36.559Z"
    assert event["event"]["action"] == "process-created"
    assert event["event"]["category"] == ["process"]
    assert event["event"]["type"] == ["start"]
    assert event["tartarus"]["lane"] == "process"
    command_line = f'"{SHELL_HOST}" -ServerName:App.AppXtk181tbxbce2qsex02s8tw7hfxa9xb3t.mca'
    assert event["process"] == {
        "pid": 2816,
        "entity_id": "6:2816@2026-10-18T22:46:38.000Z",
        "name": "ShellExperienceHost.exe",
        "executable": SHELL_HOST,
        "command_line": command_line,
        "start": "2026-10-18T22:46:38.000Z",
        "integrity_level": "AppContainer",
        "hash": {"sha256": "8662d1661b6261ad2d7081bc1ee54429e806b14b5fea4a777ba546e3c4a8352d"},
        "parent": {
            "pid": 924,
            "name": "svchost.exe",
            "executable": "C:\\Windows\\System32\\svchost.exe",
            "command_line": "C:\\WINDOWS\\system32\\svchost.exe -k DcomLaunch -p",
        },
    }
    assert event["tartarus"]["summary"] == f"svchost.exe started {command_line}"
    assert event["user"] == {"name": "Megan", "domain": "LAPTOP-PUXCRZD"}


def test_a_sysmon_event_and_a_capemon_event_of_one_process_share_the_entity_id(
    fixture_events: dict[int, Event], tmp_path: Path
) -> None:
    capemon_events = list(CapemonNormalizer().normalise(WIDE_REPORT, context_of(tmp_path)))
    capemon_entity = next(e["process"]["entity_id"] for e in capemon_events if "process" in e)

    assert fixture_events[2667]["process"]["entity_id"] == capemon_entity
    assert fixture_events[2686]["process"]["entity_id"] == capemon_entity


CHILD_PID = 501
CHILD_STARTED_AT = "2026-10-18 20:43:50.000"
CHILD_START_ON_UTC = "2026-10-18T22:43:50.000Z"


def process_created_eid1(pid: int, process_guid: str, **extra: str) -> str:
    return event_xml(
        1,
        pid,
        CHILD_STARTED_AT,
        {
            "UtcTime": CHILD_STARTED_AT,
            "ProcessGuid": process_guid,
            "ProcessId": pid,
            "Image": CMD,
            "CommandLine": CMD,
            "ParentProcessGuid": guid(1),
            "ParentProcessId": 500,
            "ParentImage": BENIGN,
            "ParentCommandLine": BENIGN,
            **extra,
        },
    )


def test_a_process_created_event_carries_the_lowercase_sha256_of_its_image(
    tmp_path: Path,
) -> None:
    hashes = "SHA1=AAAA,MD5=BBBB,SHA256=" + "4B322B00" * 8 + ",IMPHASH=CCCC"

    events = hand_written(tmp_path, process_created_eid1(CHILD_PID, guid(2), Hashes=hashes))

    assert only(events)["process"]["hash"] == {"sha256": "4b322b00" * 8}


@pytest.mark.parametrize("hashes", ["SHA1=AAAA,MD5=BBBB", "-", ""])
def test_a_process_created_event_without_a_sha256_has_no_process_hash(
    tmp_path: Path, hashes: str
) -> None:
    events = hand_written(tmp_path, process_created_eid1(CHILD_PID, guid(2), Hashes=hashes))

    assert "hash" not in only(events)["process"]


def test_a_process_created_event_without_a_hashes_field_has_no_process_hash(
    tmp_path: Path,
) -> None:
    events = hand_written(tmp_path, process_created_eid1(CHILD_PID, guid(2)))

    assert "hash" not in only(events)["process"]


def test_a_hash_on_another_event_does_not_become_a_process_hash(tmp_path: Path) -> None:
    deleted = schema_event(
        23,
        User=USER,
        TargetFilename="C:\\Users\\Megan\\Desktop\\notes.txt",
        Hashes="SHA256=" + "AB" * 32,
        **acting(),
    )

    events = hand_written(tmp_path, deleted)

    assert "hash" not in only(events)["process"]


def sample_calling(api: str, child_pid: int, **fields: Any) -> dict[str, Any]:
    started = call(api, {"ProcessId": str(child_pid), "ApplicationName": CMD}, **fields)
    return monitored(500, BENIGN, calls=[started])


def entity_ids_of_started(events: list[Event]) -> dict[int, str]:
    return {e["process"]["pid"]: e["process"]["entity_id"] for e in events}


def test_a_monitored_process_takes_capemons_start_in_its_entity_id(tmp_path: Path) -> None:
    report = report_with(
        sample_calling("CreateProcessInternalW", CHILD_PID),
        monitored(CHILD_PID, CMD, first_seen="2026-10-18 20:43:51"),
    )

    events = hand_written(tmp_path, process_created_eid1(CHILD_PID, guid(2)), report=report)

    assert entity_ids_of_started(events) == {CHILD_PID: "6:501@2026-10-18T22:43:51.000Z"}


def test_a_child_capemon_only_saw_created_has_capemons_bare_entity_id(tmp_path: Path) -> None:
    report = report_with(sample_calling("CreateProcessInternalW", CHILD_PID))

    events = hand_written(tmp_path, process_created_eid1(CHILD_PID, guid(2)), report=report)

    assert entity_ids_of_started(events) == {CHILD_PID: "6:501"}


def test_the_bare_entity_id_holds_for_every_process_creating_api(tmp_path: Path) -> None:
    report = report_with(sample_calling("NtCreateUserProcess", CHILD_PID))

    events = hand_written(tmp_path, process_created_eid1(CHILD_PID, guid(2)), report=report)

    assert entity_ids_of_started(events) == {CHILD_PID: "6:501"}


def test_a_failed_create_call_does_not_make_the_child_capemons(tmp_path: Path) -> None:
    report = report_with(sample_calling("CreateProcessInternalW", CHILD_PID, status=False))

    events = hand_written(tmp_path, process_created_eid1(CHILD_PID, guid(2)), report=report)

    assert entity_ids_of_started(events) == {CHILD_PID: f"6:501@{CHILD_START_ON_UTC}"}


def test_a_process_capemon_knows_nothing_about_keeps_sysmons_start(tmp_path: Path) -> None:
    other_pid = 502
    report = report_with(sample_calling("CreateProcessInternalW", CHILD_PID))

    events = hand_written(tmp_path, process_created_eid1(other_pid, guid(3)), report=report)

    assert entity_ids_of_started(events) == {other_pid: f"6:502@{CHILD_START_ON_UTC}"}


def test_eid_5_process_terminated(fixture_events: dict[int, Event]) -> None:
    event = fixture_events[2686]

    assert event["@timestamp"] == "2026-10-18T22:46:37.646Z"
    assert event["event"]["action"] == "process-terminated"
    assert event["event"]["type"] == ["end"]
    assert event["tartarus"]["lane"] == "process"
    assert event["process"]["pid"] == 2816
    assert event["process"]["executable"] == SHELL_HOST
    assert event["process"]["command_line"].endswith(
        "-ServerName:App.AppXtk181tbxbce2qsex02s8tw7hfxa9xb3t.mca"
    )
    assert "parent" not in event["process"]
    assert event["tartarus"]["summary"] == "ShellExperienceHost.exe terminated"


def test_eid_3_network_connection(fixture_events: dict[int, Event]) -> None:
    event = fixture_events[2662]

    # The log's write time: 1.6 s after the connection's own `UtcTime` (22:46:20.928) here.
    assert event["@timestamp"] == "2026-10-18T22:46:22.513Z"
    assert event["event"]["action"] == "network-connection"
    assert event["event"]["category"] == ["network"]
    assert event["event"]["type"] == ["connection"]
    assert event["tartarus"]["lane"] == "network"
    assert event["process"]["pid"] == 1604
    assert event["source"] == {"ip": "192.168.150.14", "port": 57043}
    assert event["destination"] == {"ip": "192.168.150.1", "port": 80, "domain": "www.inetsim.org"}
    assert event["network"] == {"transport": "tcp"}
    assert event["tartarus"]["summary"] == "svchost.exe connected to 192.168.150.1:80"


def test_eid_22_dns_query(fixture_events: dict[int, Event]) -> None:
    event = fixture_events[533]

    # The log's write time: 1 s after the query's own `UtcTime` (22:43:50.262) here.
    assert event["@timestamp"] == "2026-10-18T22:43:51.255Z"
    assert event["event"]["action"] == "dns-query"
    assert event["event"]["category"] == ["network"]
    assert event["event"]["type"] == ["protocol"]
    assert event["tartarus"]["lane"] == "network"
    assert event["process"]["pid"] == 8364
    assert event["dns"] == {
        "question": {"name": "tartarus-selftest.example"},
        "answers": {"data": ["192.168.150.1"]},
    }
    assert event["network"] == {"protocol": "dns"}
    assert event["tartarus"]["summary"] == "benign.exe resolved tartarus-selftest.example"


def test_eid_22_without_an_answer_has_no_answers(fixture_events: dict[int, Event]) -> None:
    assert fixture_events[1664]["dns"] == {"question": {"name": "wpad"}}


def test_eid_7_image_loaded(fixture_events: dict[int, Event]) -> None:
    event = fixture_events[365]

    assert event["@timestamp"] == "2026-10-18T22:43:48.633Z"
    assert event["event"]["action"] == "image-loaded"
    assert event["event"]["category"] == ["process"]
    assert event["event"]["type"] == ["info"]
    assert event["tartarus"]["lane"] == "process"
    assert event["process"]["pid"] == 8364
    assert event["file"] == {
        "path": BENIGN,
        "name": "benign.exe",
        "extension": "exe",
        "hash": {"sha256": "7633a1a233f149113d9b44133c823424cbcd5e202a200a0d1030439ed96c2476"},
    }
    assert event["tartarus"]["summary"] == f"benign.exe loaded {BENIGN}"


def test_eid_10_process_access_names_the_target(fixture_events: dict[int, Event]) -> None:
    event = fixture_events[3489]

    assert event["event"]["action"] == "process-access"
    assert event["event"]["category"] == ["process"]
    assert event["event"]["type"] == ["access"]
    assert event["tartarus"]["lane"] == "process"
    assert event["process"]["pid"] == 3872
    assert event["process"]["executable"] == "C:\\WINDOWS\\system32\\sihost.exe"
    assert event["process"]["thread"] == {"id": 3168}
    assert event["tartarus"]["inject"] == {
        "target_pid": 4300,
        "target_name": "Explorer.EXE",
        "target_executable": "C:\\WINDOWS\\Explorer.EXE",
    }
    assert (
        event["tartarus"]["summary"]
        == "sihost.exe opened Explorer.EXE (pid 4300) with access 0x1040"
    )
    assert event["user"] == {"name": "Megan", "domain": "LAPTOP-PUXCRZD"}


def test_eid_11_file_created(fixture_events: dict[int, Event]) -> None:
    event = fixture_events[2843]
    path = (
        "C:\\ProgramData\\Microsoft\\Windows\\AppRepository\\Packages\\"
        "Microsoft.Windows.ShellExperienceHost_10.0.26100.7462_neutral_neutral_cw5n1h2txyewy\\"
        "machine.pckgdep"
    )

    assert event["@timestamp"] == "2026-10-18T22:46:37.792Z"
    assert event["event"]["action"] == "file-created"
    assert event["event"]["category"] == ["file"]
    assert event["event"]["type"] == ["creation"]
    assert event["tartarus"]["lane"] == "file"
    assert event["process"]["pid"] == 3016
    assert event["file"] == {"path": path, "name": "machine.pckgdep", "extension": "pckgdep"}
    assert event["tartarus"]["summary"] == f"svchost.exe created {path}"
    assert event["user"]["name"] == "SYSTEM"


def test_eid_26_file_delete_detected(fixture_events: dict[int, Event]) -> None:
    event = fixture_events[2721]

    assert event["event"]["action"] == "file-deleted"
    assert event["event"]["type"] == ["deletion"]
    assert event["tartarus"]["lane"] == "file"
    assert event["file"]["name"] == "machine.pckgdep"
    assert event["file"]["hash"] == {
        "sha256": "d5259da3e11d6c1e60121e02ebf2c57334c124026fcb77ced155bc9d41674e74"
    }
    assert event["tartarus"]["summary"].startswith("svchost.exe deleted C:\\ProgramData\\")


def test_eid_12_create_key(fixture_events: dict[int, Event]) -> None:
    event = fixture_events[3500]
    path = "HKLM\\System\\CurrentControlSet\\Services\\Tcpip\\Parameters"

    assert event["event"]["action"] == "reg-key-created"
    assert event["event"]["category"] == ["registry"]
    assert event["event"]["type"] == ["creation"]
    assert event["tartarus"]["lane"] == "registry"
    assert event["registry"] == {
        "path": path,
        "hive": "HKLM",
        "key": "System\\CurrentControlSet\\Services\\Tcpip\\Parameters",
    }
    assert event["tartarus"]["summary"] == f"svchost.exe created key {path}"


def test_eid_12_delete_key(fixture_events: dict[int, Event]) -> None:
    event = fixture_events[3464]

    assert event["event"]["action"] == "reg-key-deleted"
    assert event["event"]["type"] == ["deletion"]
    assert event["registry"]["key"].endswith("UserAndPackage\\2^1d")
    assert event["tartarus"]["summary"].startswith("svchost.exe deleted key HKLM\\SOFTWARE\\")


def test_eid_13_set_value(fixture_events: dict[int, Event]) -> None:
    event = fixture_events[3488]
    sid = "S-1-5-21-4180615496-2325173566-1543340793-1000"
    key = f"{sid}\\Software\\Microsoft\\Windows\\CurrentVersion\\Cortana"

    assert event["event"]["action"] == "reg-value-set"
    assert event["event"]["type"] == ["change"]
    assert event["registry"] == {
        "path": f"HKU\\{key}\\IsAvailable",
        "hive": "HKU",
        "key": key,
        "value": "IsAvailable",
        "data": {"type": "REG_DWORD", "strings": ["DWORD (0x00000000)"]},
    }
    assert event["tartarus"]["summary"] == f"Explorer.EXE set HKU\\{key}\\IsAvailable"


def test_eid_13_binary_data_is_a_binary_value(fixture_events: dict[int, Event]) -> None:
    assert fixture_events[3468]["registry"]["data"] == {
        "type": "REG_BINARY",
        "strings": ["Binary Data"],
    }


# --- event ids the fixture lacks, from the Sysmon schema ------------------------------------

SCHEMA_TIME = "2026-10-18 20:44:10.000"
USER = "LAPTOP-PUXCRZD\\Megan"
SYSTEM32_SVCHOST = "C:\\Windows\\System32\\svchost.exe"


def schema_event(event_id: int, **data: str | int) -> str:
    return event_xml(event_id, 7, SCHEMA_TIME, {"RuleName": "-", "UtcTime": SCHEMA_TIME, **data})


def acting(**data: str | int) -> dict[str, str | int]:
    """The fields that name the sample's process (pid 500) as the one that acted."""
    return {"ProcessGuid": guid(1), "ProcessId": 500, "Image": BENIGN, **data}


def eid8(source: str = BENIGN, **overrides: str | int) -> str:
    data: dict[str, str | int] = {
        "SourceProcessGuid": guid(1),
        "SourceProcessId": 500,
        "SourceImage": source,
        "TargetProcessGuid": guid(2),
        "TargetProcessId": 7312,
        "TargetImage": SYSTEM32_SVCHOST,
        "NewThreadId": 1688,
        "StartAddress": "0x0000023B67A40035",
        "StartModule": "-",
        "StartFunction": "-",
        "SourceUser": USER,
        "TargetUser": "NT AUTHORITY\\SYSTEM",
    }
    return event_xml(
        8, 951, "2026-10-18 20:44:07.342", {"UtcTime": "2026-10-18 20:44:07.342"} | data | overrides
    )


REGISTRY_RENAME = schema_event(
    14,
    EventType="RenameKey",
    TargetObject="HKLM\\SOFTWARE\\Vendor\\Old",
    NewName="HKLM\\SOFTWARE\\Vendor\\New",
    User=USER,
    **acting(),
)
VALUE_DELETED = schema_event(
    12,
    EventType="DeleteValue",
    TargetObject="HKCU\\Software\\Vendor\\Run\\Updater",
    **acting(),
)
FILE_DELETED = schema_event(
    23,
    User=USER,
    TargetFilename="C:\\Users\\Megan\\Desktop\\notes.txt",
    Hashes="MD5=AAAA,SHA256=" + "AB" * 32,
    IsExecutable="false",
    Archived="true",
    **acting(),
)
INBOUND = schema_event(
    3,
    User=USER,
    Protocol="udp",
    Initiated="false",
    SourceIp="192.168.150.255",
    SourceHostname="-",
    SourcePort=138,
    DestinationIp="192.168.150.14",
    DestinationHostname="LAPTOP-PUXCRZD",
    DestinationPort=138,
    **acting(),
)
WMI_FILTER = schema_event(
    19,
    EventType="WmiFilterEvent",
    Operation="Created",
    User=USER,
    EventNamespace="root\\cimv2",
    Name="Updater",
    Query="SELECT * FROM __InstanceModificationEvent",
)
WMI_CONSUMER = schema_event(
    20,
    EventType="WmiConsumerEvent",
    Operation="Created",
    User=USER,
    Name="Updater",
    Type="Command Line",
    Destination="powershell.exe -enc AAAA",
)
WMI_BINDING = schema_event(
    21,
    EventType="WmiBindingEvent",
    Operation="Deleted",
    User=USER,
    Consumer='CommandLineEventConsumer.Name="Updater"',
    Filter='__EventFilter.Name="Updater"',
)
SCHEMA_EVENTS = (
    eid8(),
    REGISTRY_RENAME,
    VALUE_DELETED,
    FILE_DELETED,
    INBOUND,
    WMI_FILTER,
    WMI_CONSUMER,
    WMI_BINDING,
)


def test_eid_8_create_remote_thread_names_the_target(tmp_path: Path) -> None:
    event = only(hand_written(tmp_path, eid8()))

    assert event["@timestamp"] == "2026-10-18T22:44:07.342Z"
    assert event["event"]["action"] == "create-remote-thread"
    assert event["event"]["category"] == ["process"]
    assert event["event"]["type"] == ["change"]
    assert event["tartarus"]["lane"] == "process"
    assert event["process"]["pid"] == 500
    assert event["process"]["executable"] == BENIGN
    assert event["tartarus"]["inject"] == {
        "target_pid": 7312,
        "target_name": "svchost.exe",
        "target_executable": SYSTEM32_SVCHOST,
    }
    assert event["tartarus"]["summary"] == "benign.exe started a thread in svchost.exe (pid 7312)"
    assert event["user"] == {"name": "Megan", "domain": "LAPTOP-PUXCRZD"}


def test_eid_14_registry_rename(tmp_path: Path) -> None:
    event = only(hand_written(tmp_path, REGISTRY_RENAME))

    assert event["event"]["action"] == "reg-rename"
    assert event["event"]["category"] == ["registry"]
    assert event["event"]["type"] == ["change"]
    assert event["tartarus"]["lane"] == "registry"
    assert event["registry"] == {
        "path": "HKLM\\SOFTWARE\\Vendor\\Old",
        "hive": "HKLM",
        "key": "SOFTWARE\\Vendor\\Old",
    }
    assert event["tartarus"]["summary"] == (
        "benign.exe renamed HKLM\\SOFTWARE\\Vendor\\Old to HKLM\\SOFTWARE\\Vendor\\New"
    )


def test_eid_12_delete_value(tmp_path: Path) -> None:
    event = only(hand_written(tmp_path, VALUE_DELETED))

    assert event["event"]["action"] == "reg-value-deleted"
    assert event["event"]["type"] == ["deletion"]
    assert event["registry"] == {
        "path": "HKCU\\Software\\Vendor\\Run\\Updater",
        "hive": "HKCU",
        "key": "Software\\Vendor\\Run",
        "value": "Updater",
    }
    assert (
        event["tartarus"]["summary"]
        == "benign.exe deleted value HKCU\\Software\\Vendor\\Run\\Updater"
    )


def test_eid_23_file_delete_is_a_file_deleted_event(tmp_path: Path) -> None:
    event = only(hand_written(tmp_path, FILE_DELETED))

    assert event["event"]["action"] == "file-deleted"
    assert event["event"]["type"] == ["deletion"]
    assert event["file"] == {
        "path": "C:\\Users\\Megan\\Desktop\\notes.txt",
        "name": "notes.txt",
        "extension": "txt",
        "hash": {"sha256": "ab" * 32},
    }
    assert event["tartarus"]["summary"] == "benign.exe deleted C:\\Users\\Megan\\Desktop\\notes.txt"


def test_inbound_connection_reads_source_as_the_remote_end(tmp_path: Path) -> None:
    event = only(hand_written(tmp_path, INBOUND))

    assert event["source"] == {"ip": "192.168.150.255", "port": 138}
    assert event["destination"] == {"ip": "192.168.150.14", "port": 138}
    assert event["network"] == {"transport": "udp"}
    assert (
        event["tartarus"]["summary"] == "benign.exe accepted a connection from 192.168.150.255:138"
    )


def test_eid_19_wmi_filter(tmp_path: Path) -> None:
    event = only(hand_written(tmp_path, WMI_FILTER))

    assert event["event"]["action"] == "wmi-filter"
    assert event["event"]["category"] == ["process"]
    assert event["event"]["type"] == ["creation"]
    assert event["tartarus"]["lane"] == "process"
    assert "process" not in event
    assert event["tartarus"]["summary"] == (
        "WMI event filter Updater created in root\\cimv2: SELECT * FROM __InstanceModificationEvent"
    )
    assert event["user"] == {"name": "Megan", "domain": "LAPTOP-PUXCRZD"}


def test_eid_20_wmi_consumer(tmp_path: Path) -> None:
    event = only(hand_written(tmp_path, WMI_CONSUMER))

    assert event["event"]["action"] == "wmi-consumer"
    assert event["event"]["type"] == ["creation"]
    assert event["tartarus"]["summary"] == (
        "WMI event consumer Updater (Command Line) created: powershell.exe -enc AAAA"
    )


def test_eid_21_wmi_binding(tmp_path: Path) -> None:
    event = only(hand_written(tmp_path, WMI_BINDING))

    assert event["event"]["action"] == "wmi-binding"
    assert event["event"]["type"] == ["deletion"]
    assert event["tartarus"]["summary"] == (
        'WMI binding of CommandLineEventConsumer.Name="Updater" '
        'to __EventFilter.Name="Updater" deleted'
    )


def test_every_schema_event_keeps_the_contract(tmp_path: Path) -> None:
    root = analysis_with(tmp_path, *SCHEMA_EVENTS)

    events = check_normalizer_contract(
        SysmonNormalizer(), report_with(monitored(500, BENIGN)), context_of(root)
    )

    assert len(events) == len(SCHEMA_EVENTS)


# --- time, order, identity, robustness ----------------------------------------------------


def test_output_is_oldest_first_though_the_fixture_is_newest_first(
    fixture_events: dict[int, Event],
) -> None:
    events = sorted(fixture_events.values(), key=lambda event: event["event"]["sequence"])
    stamps = [event["@timestamp"] for event in events]

    assert stamps == sorted(stamps)
    assert [e["event"]["sequence"] for e in events] == list(range(len(events)))


def test_event_ids_are_unique(tmp_path: Path) -> None:
    events = hand_written(tmp_path, eid8(), eid8(NewThreadId=1))

    assert len({event["event"]["id"] for event in events}) == 2


def test_event_id_follows_the_position_in_the_file_not_in_the_output(tmp_path: Path) -> None:
    kept = eid8()
    after_one_background = hand_written(tmp_path / "a", background_file_event(1), kept)
    after_another = hand_written(tmp_path / "b", background_file_event(2), kept)
    first_in_file = hand_written(tmp_path / "c", kept)

    assert after_one_background[0]["event"]["id"] == after_another[0]["event"]["id"]
    assert after_one_background[0]["event"]["id"] != first_in_file[0]["event"]["id"]


def background_file_event(record_id: int) -> str:
    return event_xml(
        11,
        record_id,
        "2026-10-18 20:44:00.000",
        {
            "UtcTime": "2026-10-18 20:44:00.000",
            "ProcessGuid": guid(9),
            "ProcessId": 9999,
            "Image": "C:\\Windows\\System32\\svchost.exe",
            "TargetFilename": f"C:\\Windows\\Temp\\{record_id}.tmp",
        },
    )


def test_a_missing_utc_time_falls_back_to_the_log_time(tmp_path: Path) -> None:
    xml = event_xml(
        5,
        7,
        "2026-10-18 20:44:10.250",
        {"ProcessGuid": guid(1), "ProcessId": 500, "Image": BENIGN},
    )

    assert only(hand_written(tmp_path, xml))["@timestamp"] == "2026-10-18T22:44:10.250Z"


@pytest.mark.parametrize(
    ("event_id", "data"),
    [
        (22, {"QueryName": "example.test", "QueryResults": "10.0.0.1;"}),
        (3, {"DestinationIp": "10.0.0.1", "DestinationPort": 80, "Protocol": "tcp"}),
    ],
    ids=["dns-query", "network-connection"],
)
def test_events_whose_utc_time_does_not_follow_the_clock_step_take_the_log_time(
    tmp_path: Path, event_id: int, data: dict[str, str | int]
) -> None:
    # Seen in the M8 real run: CAPE steps the guest clock forward (here by two minutes) when the
    # analysis starts. EID 3 and 22 are built from ETW timestamps that do not move with it, so
    # their `UtcTime` was two minutes before the sample started; `TimeCreated` is right.
    stale = "2026-10-18 20:44:10.000"
    log_time = "2026-10-18 20:46:10.000"
    xml = event_xml(
        event_id,
        7,
        log_time,
        {"UtcTime": stale, "ProcessGuid": guid(1), "ProcessId": 500, "Image": BENIGN, **data},
    )

    assert only(hand_written(tmp_path, xml))["@timestamp"] == "2026-10-18T22:46:10.000Z"


def test_an_event_without_any_time_takes_the_analysis_start(tmp_path: Path) -> None:
    xml = (
        "<Event xmlns='http://schemas.microsoft.com/win/2004/08/events/event'><System>"
        "<EventID>5</EventID></System><EventData><Data Name='ProcessId'>500</Data>"
        f"<Data Name='Image'>{BENIGN}</Data></EventData></Event>"
    )

    assert only(hand_written(tmp_path, xml))["@timestamp"] == "2026-10-18T22:43:30.000Z"


def test_without_a_monitored_process_the_events_are_brought_onto_the_run_by_the_export_clock(
    tmp_path: Path,
) -> None:
    # A sample Defender removed before it ran: capemon saw nothing, so the guest clock is read off
    # the export, whose last record is seconds before `info.ended` (two hours ahead).
    started = event_xml(
        1,
        1,
        "2026-10-18 20:43:49.000",
        {
            "UtcTime": "2026-10-18 20:43:49.000",
            "ProcessGuid": guid(1),
            "ProcessId": 500,
            "Image": BENIGN,
            "CommandLine": BENIGN,
        },
    )
    last = event_xml(
        5,
        2,
        "2026-10-18 20:44:10.250",
        {"UtcTime": "2026-10-18 20:44:10.250", "ProcessGuid": guid(1), "ProcessId": 500},
    )
    report = {
        **report_with(),
        "target": {"file": {"name": "benign.exe"}},
        "info": {"started": "2026-10-18 22:43:30", "ended": "2026-10-18 22:44:21"},
    }

    events = by_record(hand_written(tmp_path, started, last, report=report))

    assert events[1]["@timestamp"] == "2026-10-18T22:43:49.000Z"
    assert events[2]["@timestamp"] == "2026-10-18T22:44:10.250Z"


def test_data_is_read_by_name_not_by_position(tmp_path: Path) -> None:
    shuffled = event_xml(
        22,
        7,
        "2026-10-18 20:44:10.000",
        {
            "Image": BENIGN,
            "QueryResults": "10.0.0.1;",
            "QueryName": "example.test",
            "ProcessId": 500,
            "UtcTime": "2026-10-18 20:44:10.000",
            "ProcessGuid": guid(1),
        },
    )

    event = only(hand_written(tmp_path, shuffled))

    assert event["dns"]["question"]["name"] == "example.test"
    assert event["dns"]["answers"]["data"] == ["10.0.0.1"]


def test_a_dns_answer_list_is_split_on_semicolons(tmp_path: Path) -> None:
    xml = event_xml(
        22,
        7,
        "2026-10-18 20:44:10.000",
        {
            "UtcTime": "2026-10-18 20:44:10.000",
            "ProcessGuid": guid(1),
            "ProcessId": 500,
            "QueryName": "example.test",
            "QueryResults": "::ffff:10.0.0.1;type: 5 alias.example.test;",
            "Image": BENIGN,
        },
    )

    assert only(hand_written(tmp_path, xml))["dns"]["answers"]["data"] == [
        "::ffff:10.0.0.1",
        "type: 5 alias.example.test",
    ]


def test_a_long_command_line_is_cut_in_the_summary_only(tmp_path: Path) -> None:
    long_line = "benign.exe " + "A" * 2000
    xml = event_xml(
        1,
        7,
        "2026-10-18 20:44:10.000",
        {
            "UtcTime": "2026-10-18 20:44:10.000",
            "ProcessGuid": guid(1),
            "ProcessId": 500,
            "Image": BENIGN,
            "CommandLine": long_line,
            "ParentProcessGuid": guid(8),
            "ParentProcessId": 4,
            "ParentImage": "C:\\Windows\\explorer.exe",
        },
    )

    event = only(hand_written(tmp_path, xml))

    assert event["process"]["command_line"] == long_line
    assert len(event["tartarus"]["summary"]) <= 300
    assert event["tartarus"]["summary"].endswith("…")


def test_the_original_record_is_kept(fixture_events: dict[int, Event]) -> None:
    raw = fixture_events[2662]["tartarus"]["raw"]

    assert raw["EventID"] == 3
    assert raw["EventData"]["DestinationIp"] == "192.168.150.1"


def test_cp1250_bytes_in_the_export_do_not_stop_the_run(fixture_events: dict[int, Event]) -> None:
    domain = fixture_events[2843]["user"]["domain"]

    assert domain.startswith("ZARZ")
    assert domain.endswith("DZANIE NT")


def test_event_ids_sysmon_does_not_map_are_counted_not_emitted(tmp_path: Path) -> None:
    normalizer = SysmonNormalizer()
    root = analysis_with(
        tmp_path,
        event_xml(17, 1, "2026-10-18 20:44:10.000", {"ProcessId": 500, "PipeName": "\\x"}),
        event_xml(4, 2, "2026-10-18 20:44:11.000", {"State": "Started"}),
        event_xml(16, 3, "2026-10-18 20:44:12.000", {"Configuration": "x"}),
    )

    events = list(normalizer.normalise(report_with(monitored(500, BENIGN)), context_of(root)))

    assert events == []
    assert dict(normalizer.dropped) == {"sysmon-service": 2, "unmapped-event": 1}


def test_an_event_with_no_pid_has_no_process_section(tmp_path: Path) -> None:
    xml = event_xml(
        13,
        7,
        "2026-10-18 20:44:10.000",
        {
            "EventType": "SetValue",
            "UtcTime": "2026-10-18 20:44:10.000",
            "Image": BENIGN,
            "TargetObject": "HKCU\\Software\\X\\Y",
            "Details": "(Empty)",
        },
    )

    assert "process" not in only(hand_written(tmp_path, xml))


# --- size --------------------------------------------------------------------------------


STREAMED_BYTES = 20 * 1024 * 1024
MEMORY_BUDGET_BYTES = 12 * 1024 * 1024


def write_background_log(root: Path, sample_events: list[str], size: int) -> Path:
    """A log of `size` bytes: background file events with the sample's scattered among them."""
    background = background_file_event(1)
    export = root / "sysmon"
    export.mkdir(parents=True)
    path = export / "sysmon.xml"
    with path.open("w", encoding="utf-8") as handle:
        handle.write("<Events>\n")
        written = 0
        while written < size:
            handle.write(background + "\n")
            written += len(background) + 1
            if sample_events and written % 7 == 0:
                handle.write(sample_events.pop() + "\n")
        for leftover in sample_events:
            handle.write(leftover + "\n")
        handle.write("</Events>\n")
    return root


PEAK_MEMORY_PROBE = """
import re
import sys
from pathlib import Path

from app.ingest.sysmon import SysmonNormalizer
from tests.ingest.sysmon_cases import BENIGN, context_of, monitored, report_with

normalizer = SysmonNormalizer()
report = report_with(monitored(500, BENIGN))
emitted = sum(1 for _ in normalizer.normalise(report, context_of(Path(sys.argv[1]))))
# VmHWM, not getrusage: ru_maxrss is inherited from the parent across exec.
peak_kib = int(re.search(r"VmHWM:\\s+(\\d+) kB", Path("/proc/self/status").read_text())[1])
print(emitted, normalizer.dropped["windows-background"], peak_kib)
"""
BACKEND = Path(__file__).parents[2]


def probe_peak_memory(root: Path) -> tuple[int, int, int]:
    """Events emitted, background dropped, and peak resident KiB of a fresh interpreter (Linux)."""
    result = subprocess.run(  # noqa: S603
        [sys.executable, "-c", PEAK_MEMORY_PROBE, str(root)],
        cwd=BACKEND,
        capture_output=True,
        text=True,
        check=True,
    )
    emitted, background, peak_kib = (int(value) for value in result.stdout.split())
    return emitted, background, peak_kib


def test_a_log_of_twenty_megabytes_is_streamed_not_held(tmp_path: Path) -> None:
    big = write_background_log(
        tmp_path / "big", [eid8(NewThreadId=n) for n in range(40)], STREAMED_BYTES
    )
    small = write_background_log(tmp_path / "small", [eid8()], 100_000)
    assert (big / "sysmon" / "sysmon.xml").stat().st_size >= STREAMED_BYTES

    emitted, background, big_peak = probe_peak_memory(big)
    _, _, small_peak = probe_peak_memory(small)

    assert emitted == 40
    assert background > 10_000
    assert (big_peak - small_peak) * 1024 < MEMORY_BUDGET_BYTES
