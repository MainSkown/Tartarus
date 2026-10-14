from datetime import UTC, datetime
from typing import Any

from app.db.models.analysis import Severity
from app.events.event_model import event_from_source
from app.schemas.events_api import EventDestination, EventProcess


def api_call() -> dict[str, Any]:
    return {
        "@timestamp": "2026-10-13T12:12:41.383Z",
        "event": {
            "id": "abc",
            "sequence": 7,
            "kind": "event",
            "category": ["process"],
            "action": "api-call",
            "module": "capemon",
            "dataset": "capemon.api",
            "severity": 0,
        },
        "tartarus": {"lane": "api", "summary": "NtOpenKey"},
        "process": {"pid": 10116, "name": "benign.exe", "entity_id": "6:10116@x"},
        "api": {"name": "NtOpenKey", "arguments": {"KeyHandle": "0x1"}},
    }


def test_an_api_call_maps_to_the_fields_the_table_shows() -> None:
    event = event_from_source(api_call())

    assert event.id == "abc"
    assert event.time == datetime(2026, 10, 13, 12, 12, 41, 383_000, tzinfo=UTC)
    assert (event.sequence, event.lane, event.kind, event.action) == (7, "api", "event", "api-call")
    assert (event.module, event.dataset, event.summary) == ("capemon", "capemon.api", "NtOpenKey")
    assert event.category == ["process"]
    assert event.severity is Severity.INFO
    assert event.process == EventProcess(pid=10116, name="benign.exe", entity_id="6:10116@x")
    assert event.api_name == "NtOpenKey"


def test_what_a_document_lacks_is_null_and_lists_are_empty() -> None:
    event = event_from_source({"@timestamp": "2026-10-13T12:12:41Z", "event": {"id": "x"}})

    assert event.process is None
    assert event.destination is None
    assert event.category == []
    assert (event.sequence, event.lane, event.severity, event.summary) == (None, None, None, None)


def test_a_network_event_carries_its_destination_dns_and_url() -> None:
    source = {
        "@timestamp": "2026-10-13T12:12:41Z",
        "event": {"id": "n"},
        "destination": {"ip": "1.2.3.4", "port": 443, "domain": "a.example"},
        "dns": {"question": {"name": "a.example"}},
        "url": {"full": "http://a.example/x"},
    }

    event = event_from_source(source)

    assert event.destination == EventDestination(ip="1.2.3.4", port=443, domain="a.example")
    assert event.dns_query == "a.example"
    assert event.url == "http://a.example/x"


def test_an_alert_carries_its_rule_and_a_severity_name() -> None:
    source = {
        "@timestamp": "2026-10-13T12:12:41Z",
        "event": {"id": "a", "kind": "alert", "severity": 3},
        "rule": {"name": "creates_exe", "ruleset": "cape"},
    }

    event = event_from_source(source)

    assert (event.rule_name, event.rule_ruleset) == ("creates_exe", "cape")
    assert event.severity is Severity.HIGH


def test_file_and_registry_paths_are_carried() -> None:
    source = {
        "@timestamp": "2026-10-13T12:12:41Z",
        "event": {"id": "f"},
        "file": {"path": "C:\\a.txt"},
        "registry": {"path": "HKLM\\x"},
    }

    event = event_from_source(source)

    assert (event.file_path, event.registry_path) == ("C:\\a.txt", "HKLM\\x")
