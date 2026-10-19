"""One action seen by both capemon and Sysmon raises one Sigma alert, not two.

capemon derives an event from the API call and Sysmon logs the same action, so both sources
emit an event for it. The suppression window is per (rule, `process.entity_id`), so the claim
holds only when both sources give the process the same entity id. The ingester runs over a
report and a Sysmon export here, so the claim is checked on the real pipeline.
"""

import json
from pathlib import Path
from typing import Any

from app.ingest.ingester import ReportIngester
from app.rules.loader import load_rule_file
from app.rules.rule import Rule
from tests.ingest.conftest import ANALYSIS_ID
from tests.ingest.fake_index import FakeIndex
from tests.ingest.reports import call
from tests.ingest.sysmon_cases import analysis_with, event_xml, guid, monitored, report_with
from tests.rules.support import rule_yaml, simple_detection

Event = dict[str, Any]

SAMPLE = r"C:\Users\Megan\AppData\Local\Temp\sample.exe"
CHILD = r"C:\Windows\System32\whoami.exe"
SAMPLE_PID = 700
CHILD_PID = 701
OTHER_PID = 702
SAMPLE_GUID = guid(10)
CHILD_GUID = guid(11)
C2 = "192.168.150.1"
SAMPLE_FIRST_SEEN = "2026-10-18 20:43:49,000"
CHILD_FIRST_SEEN = "2026-10-18 20:43:50,000"
ACTION_UTC = "2026-10-18 20:43:50"
ACTION_TIME = f"{ACTION_UTC}.000"
CHILD_ENTITY = f"6:{CHILD_PID}@2026-10-18T22:43:50.000Z"
UNMONITORED_CHILD_ENTITY = f"6:{CHILD_PID}"


def rule_of(tmp_path: Path, category: str, selection: str) -> Rule:
    path = tmp_path / "rule.yml"
    path.write_text(
        rule_yaml(simple_detection(selection), category=category, title="Overlap"),
        encoding="utf-8",
    )
    return load_rule_file(path)


def network_rule(tmp_path: Path) -> Rule:
    return rule_of(tmp_path, "network_connection", f"DestinationIp: '{C2}'")


def creation_rule(tmp_path: Path) -> Rule:
    return rule_of(tmp_path, "process_creation", "Image|endswith: '\\whoami.exe'")


def sysmon_event(event_id: int, record_id: int, data: dict[str, str | int]) -> str:
    return event_xml(event_id, record_id, ACTION_TIME, {"UtcTime": ACTION_TIME, **data})


def connection_eid3(record_id: int, pid: int, image: str, process_guid: str) -> str:
    return sysmon_event(
        3,
        record_id,
        {
            "ProcessGuid": process_guid,
            "ProcessId": pid,
            "Image": image,
            "Protocol": "tcp",
            "DestinationIp": C2,
            "DestinationPort": 80,
        },
    )


def child_started_eid1(record_id: int) -> str:
    return sysmon_event(
        1,
        record_id,
        {
            "ProcessGuid": CHILD_GUID,
            "ProcessId": CHILD_PID,
            "Image": CHILD,
            "CommandLine": CHILD,
            "ParentProcessGuid": SAMPLE_GUID,
            "ParentProcessId": SAMPLE_PID,
            "ParentImage": SAMPLE,
            "ParentCommandLine": SAMPLE,
        },
    )


def sample_started_eid1(record_id: int) -> str:
    return sysmon_event(
        1,
        record_id,
        {
            "ProcessGuid": SAMPLE_GUID,
            "ProcessId": SAMPLE_PID,
            "Image": SAMPLE,
            "CommandLine": SAMPLE,
            "ParentProcessGuid": guid(99),
            "ParentProcessId": 4,
            "ParentImage": "System",
            "ParentCommandLine": "System",
        },
    )


def connect_call() -> dict[str, Any]:
    return call("connect", {"ip": C2, "port": "80"}, timestamp=f"{ACTION_UTC},000")


def create_child_call() -> dict[str, Any]:
    return call(
        "CreateProcessInternalW",
        {"ProcessId": str(CHILD_PID), "ApplicationName": CHILD, "CommandLine": CHILD},
        timestamp=f"{ACTION_UTC},000",
    )


async def ingest(
    tmp_path: Path, processes: list[dict[str, Any]], sysmon: list[str], rule: Rule
) -> FakeIndex:
    report_path = tmp_path / "reports" / "report.json"
    report_path.parent.mkdir(parents=True)
    report_path.write_text(json.dumps(report_with(*processes)), encoding="utf-8")
    if sysmon:
        analysis_with(tmp_path, *sysmon)
    index = FakeIndex()
    await ReportIngester(index, rules=lambda: [rule]).ingest(ANALYSIS_ID, report_path)
    return index


def from_source(index: FakeIndex, source: str, action: str) -> list[Event]:
    return [
        event
        for event in index.events
        if event["event"]["action"] == action and event["event"]["dataset"].startswith(source)
    ]


def alerts(index: FakeIndex) -> list[Event]:
    return [event for event in index.events if event["event"]["kind"] == "alert"]


def alert_entity_ids(index: FakeIndex) -> list[str]:
    return sorted(alert["process"]["entity_id"] for alert in alerts(index))


# --- network connection: capemon's connect and Sysmon's EID 3 for the same process -----------


async def test_capemon_and_sysmon_both_index_the_network_connection(tmp_path: Path) -> None:
    index = await ingest(
        tmp_path,
        [monitored(SAMPLE_PID, SAMPLE, first_seen=SAMPLE_FIRST_SEEN, calls=[connect_call()])],
        [connection_eid3(1, SAMPLE_PID, SAMPLE, SAMPLE_GUID)],
        network_rule(tmp_path),
    )

    assert from_source(index, "capemon", "network-connection")
    assert from_source(index, "sysmon", "network-connection")


async def test_the_network_action_raises_one_alert_repeated_once(tmp_path: Path) -> None:
    index = await ingest(
        tmp_path,
        [monitored(SAMPLE_PID, SAMPLE, first_seen=SAMPLE_FIRST_SEEN, calls=[connect_call()])],
        [connection_eid3(1, SAMPLE_PID, SAMPLE, SAMPLE_GUID)],
        network_rule(tmp_path),
    )

    [alert] = alerts(index)
    assert alert["tartarus"]["detection"]["repeated"] == 1


# --- process creation: capemon's CreateProcessInternalW and Sysmon's EID 1 for the child ----


async def test_a_monitored_child_raises_one_alert_repeated_once(tmp_path: Path) -> None:
    index = await ingest(
        tmp_path,
        [
            monitored(
                SAMPLE_PID, SAMPLE, first_seen=SAMPLE_FIRST_SEEN, calls=[create_child_call()]
            ),
            monitored(CHILD_PID, CHILD, first_seen=CHILD_FIRST_SEEN),
        ],
        [sample_started_eid1(1), child_started_eid1(2)],
        creation_rule(tmp_path),
    )

    [alert] = alerts(index)
    assert alert["process"]["entity_id"] == CHILD_ENTITY
    assert alert["tartarus"]["detection"]["repeated"] == 1


async def test_an_unmonitored_child_raises_one_alert_repeated_once(tmp_path: Path) -> None:
    index = await ingest(
        tmp_path,
        [monitored(SAMPLE_PID, SAMPLE, first_seen=SAMPLE_FIRST_SEEN, calls=[create_child_call()])],
        [sample_started_eid1(1), child_started_eid1(2)],
        creation_rule(tmp_path),
    )

    [alert] = alerts(index)
    assert alert["tartarus"]["detection"]["repeated"] == 1


async def test_an_unmonitored_child_has_the_same_entity_id_in_both_sources(
    tmp_path: Path,
) -> None:
    index = await ingest(
        tmp_path,
        [monitored(SAMPLE_PID, SAMPLE, first_seen=SAMPLE_FIRST_SEEN, calls=[create_child_call()])],
        [sample_started_eid1(1), child_started_eid1(2)],
        creation_rule(tmp_path),
    )

    assert alert_entity_ids(index) == [UNMONITORED_CHILD_ENTITY]


# --- Sysmon-only: a child of a monitored process that capemon never listed --------------------


async def test_a_sysmon_only_child_of_the_sample_raises_one_alert_without_repeats(
    tmp_path: Path,
) -> None:
    index = await ingest(
        tmp_path,
        [monitored(SAMPLE_PID, SAMPLE, first_seen=SAMPLE_FIRST_SEEN)],
        [sample_started_eid1(1), child_started_eid1(2)],
        creation_rule(tmp_path),
    )

    [alert] = alerts(index)
    assert alert["process"]["entity_id"] == CHILD_ENTITY
    assert "repeated" not in alert["tartarus"]["detection"]


# --- control: the same action in two different processes is two alerts ----------------------


async def test_two_processes_matching_the_same_rule_are_two_alerts(tmp_path: Path) -> None:
    index = await ingest(
        tmp_path,
        [
            monitored(SAMPLE_PID, SAMPLE, first_seen=SAMPLE_FIRST_SEEN, calls=[connect_call()]),
            monitored(OTHER_PID, SAMPLE, first_seen=SAMPLE_FIRST_SEEN, calls=[connect_call()]),
        ],
        [],
        network_rule(tmp_path),
    )

    assert alert_entity_ids(index) == sorted(
        [f"6:{SAMPLE_PID}@2026-10-18T22:43:49.000Z", f"6:{OTHER_PID}@2026-10-18T22:43:49.000Z"]
    )
    assert all("repeated" not in alert["tartarus"]["detection"] for alert in alerts(index))
