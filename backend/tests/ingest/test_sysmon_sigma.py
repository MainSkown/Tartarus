"""Sysmon events are matched by the same Sigma rules as the other sources' events."""

from pathlib import Path
from typing import Any

import pytest

from app.ingest.sysmon import SysmonNormalizer
from app.rules.engine import Emit, SigmaEngine
from app.rules.loader import load_rule_file
from app.rules.rule import Rule
from tests.ingest.sysmon_cases import (
    BENIGN,
    WIDE_REPORT,
    analysis_with,
    analysis_with_fixture,
    context_of,
    monitored,
    report_with,
)
from tests.ingest.test_sysmon import SCHEMA_EVENTS
from tests.rules.support import rule_yaml, simple_detection

Event = dict[str, Any]

# (logsource category, selection, record id of the fixture event it must fire on)
FIXTURE_CASES = [
    ("process_creation", "Image|endswith: '\\ShellExperienceHost.exe'", 2667),
    (
        "process_creation",
        "ParentImage|endswith: '\\svchost.exe'\nParentCommandLine|contains: DcomLaunch",
        2667,
    ),
    (
        "network_connection",
        "DestinationIp: '192.168.150.1'\nDestinationPort: 80\nImage|endswith: '\\svchost.exe'",
        2662,
    ),
    (
        "dns_query",
        "QueryName: 'tartarus-selftest.example'\nQueryResults|contains: '192.168.150.1'",
        533,
    ),
    ("file_event", "TargetFilename|endswith: '\\machine.pckgdep'", 2843),
    (
        "registry_set",
        "TargetObject|endswith: '\\Cortana\\IsAvailable'\n"
        "Details: 'DWORD (0x00000000)'\nEventType: SetValue",
        3488,
    ),
    ("registry_add", "TargetObject|endswith: '\\Tcpip\\Parameters'\nEventType: CreateKey", 3500),
    ("registry_delete", "TargetObject|endswith: '\\2^1d'\nEventType: DeleteKey", 3464),
]


def rule_of(tmp_path: Path, category: str, selection: str, name: str) -> Rule:
    text = rule_yaml(simple_detection(selection), category=category)
    path = tmp_path / f"{name}.yml"
    path.write_text(text, encoding="utf-8")
    return load_rule_file(path)


def fires(rule: Rule, event: Event) -> bool:
    engine = SigmaEngine([rule], context_of(None), phase="final")
    return any(isinstance(outcome, Emit) for outcome in engine.process(event))


@pytest.fixture(scope="module")
def fixture_events(tmp_path_factory: pytest.TempPathFactory) -> dict[int, Event]:
    root = analysis_with_fixture(tmp_path_factory.mktemp("analysis"))
    events = SysmonNormalizer().normalise(WIDE_REPORT, context_of(root))
    return {event["tartarus"]["raw"]["EventRecordID"]: event for event in events}


@pytest.mark.parametrize(("category", "selection", "record_id"), FIXTURE_CASES)
def test_a_rule_fires_on_the_sysmon_event_of_its_category(
    tmp_path: Path,
    fixture_events: dict[int, Event],
    category: str,
    selection: str,
    record_id: int,
) -> None:
    rule = rule_of(tmp_path, category, selection, "rule")

    assert fires(rule, fixture_events[record_id])


def test_a_remote_thread_rule_fires_on_eid_8(tmp_path: Path) -> None:
    rule = rule_of(
        tmp_path,
        "create_remote_thread",
        "SourceImage|endswith: '\\benign.exe'\nTargetImage|endswith: '\\svchost.exe'",
        "thread",
    )
    root = analysis_with(tmp_path / "log", SCHEMA_EVENTS[0])
    event = next(
        SysmonNormalizer().normalise(report_with(monitored(500, BENIGN)), context_of(root))
    )

    assert fires(rule, event)


def test_a_rule_does_not_fire_on_another_category(
    tmp_path: Path, fixture_events: dict[int, Event]
) -> None:
    rule = rule_of(tmp_path, "process_creation", "Image|endswith: '\\machine.pckgdep'", "rule")

    assert not fires(rule, fixture_events[2843])
