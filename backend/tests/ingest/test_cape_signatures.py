import copy
from typing import Any

import pytest

from app.ingest.cape_signatures import CapeSignaturesNormalizer
from app.ingest.capemon import CapemonNormalizer
from app.ingest.ecs import MATCH_LIMIT, event_id
from app.ingest.protocol import IngestContext
from tests.ingest.reports import call, process, report_of

Event = dict[str, Any]
LATE = "2026-10-13 10:12:43,000"
EARLY = "2026-10-13 10:12:42,000"
ANALYSIS_END = "2026-10-13T12:13:13.000Z"


def normalise(report: dict[str, Any], context: IngestContext) -> list[Event]:
    return list(CapeSignaturesNormalizer().normalise(report, context))


def alert_named(alerts: list[Event], name: str) -> Event:
    [alert] = [alert for alert in alerts if alert["rule"]["name"] == name]
    return alert


@pytest.fixture
def alerts(full_report: dict[str, Any], context: IngestContext) -> list[Event]:
    return normalise(full_report, context)


@pytest.fixture
def capemon_events(full_report: dict[str, Any], context: IngestContext) -> list[Event]:
    return list(CapemonNormalizer().normalise(full_report, context))


def test_source_is_cape_signatures() -> None:
    assert CapeSignaturesNormalizer().source == "cape-signatures"


# --- the real report -----------------------------------------------------------------------


def test_one_alert_per_signature(full_report: dict[str, Any], alerts: list[Event]) -> None:
    assert len(alerts) == len(full_report["signatures"]) == 12
    assert {a["rule"]["name"] for a in alerts} == {s["name"] for s in full_report["signatures"]}


def test_every_alert_is_a_cape_signature_alert(alerts: list[Event]) -> None:
    for alert in alerts:
        assert alert["event"]["kind"] == "alert"
        assert alert["event"]["module"] == "cape"
        assert alert["event"]["dataset"] == "cape.signature"
        assert alert["event"]["action"] == "signature-matched"
        assert alert["event"]["category"] == ["malware"]
        assert alert["event"]["type"] == ["indicator"]
        assert alert["rule"]["ruleset"] == "cape"


def test_ids_come_from_the_position_in_the_signature_list(
    full_report: dict[str, Any], alerts: list[Event]
) -> None:
    for position, signature in enumerate(full_report["signatures"]):
        alert = alert_named(alerts, signature["name"])
        assert alert["event"]["id"] == event_id(6, "cape-signatures", "signatures", position)


def test_the_rule_carries_name_description_and_references(
    full_report: dict[str, Any], alerts: list[Event]
) -> None:
    alert = alert_named(alerts, "queries_locale_api")
    assert alert["rule"] == {
        "name": "queries_locale_api",
        "description": "Queries the computer locale (possible geofencing)",
        "ruleset": "cape",
    }
    assert alert["tartarus"]["summary"] == "Queries the computer locale (possible geofencing)"
    assert alert["tartarus"]["raw"] == full_report["signatures"][0]


def test_severity_follows_the_cape_scale(alerts: list[Event]) -> None:
    severities = {a["rule"]["name"]: a["event"]["severity"] for a in alerts}
    assert severities["queries_locale_api"] == 1
    assert severities["network_http"] == 2
    assert severities["recon_systeminfo"] == 3


def test_every_attack_technique_of_the_report_appears_on_an_alert(
    full_report: dict[str, Any], alerts: list[Event]
) -> None:
    expected = {tid for entry in full_report["ttps"] for tid in entry["ttps"]}
    found = {
        tid
        for alert in alerts
        for tid in alert.get("threat", {}).get("technique", {}).get("id", [])
    }
    assert expected == found
    assert len(expected) == 10


def test_a_signature_with_several_techniques_lists_them_in_report_order(
    alerts: list[Event],
) -> None:
    assert alert_named(alerts, "stealth_window")["threat"]["technique"]["id"] == [
        "T1564.003",
        "T1564",
    ]
    assert "threat" not in alert_named(alerts, "queries_locale_api")


def test_related_events_are_the_capemon_api_events_of_the_referenced_calls(
    full_report: dict[str, Any], alerts: list[Event], capemon_events: list[Event]
) -> None:
    api_ids = {
        (e["process"]["pid"], e["tartarus"]["raw"]["id"]): e["event"]["id"]
        for e in capemon_events
        if e["event"]["action"] == "api-call"
    }
    checked = 0
    for signature in full_report["signatures"]:
        references = [(d["pid"], d["cid"]) for d in signature["data"] if d.get("type") == "call"]
        alert = alert_named(alerts, signature["name"])
        assert sorted(alert.get("related", {}).get("events", [])) == sorted(
            api_ids[reference] for reference in references
        )
        checked += len(references)
    assert checked == 15


def test_a_call_reference_resolves_to_the_event_of_that_process_and_call(
    alerts: list[Event], capemon_events: list[Event]
) -> None:
    [linked] = alert_named(alerts, "queries_locale_api")["related"]["events"]
    event = next(e for e in capemon_events if e["event"]["id"] == linked)
    assert event["api"]["name"] == "GetUserDefaultLCID"
    assert (event["process"]["pid"], event["tartarus"]["raw"]["id"]) == (9632, 108)


def test_the_alert_happens_when_its_earliest_referenced_call_did(
    alerts: list[Event], capemon_events: list[Event]
) -> None:
    for alert in alerts:
        linked = alert.get("related", {}).get("events", [])
        if linked:
            stamps = [e["@timestamp"] for e in capemon_events if e["event"]["id"] in linked]
            assert alert["@timestamp"] == min(stamps)


def test_an_alert_without_call_references_happens_at_the_analysis_end(alerts: list[Event]) -> None:
    alert = alert_named(alerts, "network_http")
    assert "related" not in alert
    assert alert["@timestamp"] == ANALYSIS_END


def test_the_lane_is_that_of_the_first_referenced_call_else_process(
    alerts: list[Event],
) -> None:
    assert {alert["tartarus"]["lane"] for alert in alerts} == {"process"}


def test_the_match_text_lists_the_non_call_data(alerts: list[Event]) -> None:
    registry = alert_named(alerts, "language_check_registry")
    assert registry["tartarus"]["detection"]["match"] == (
        "regkey: HKEY_LOCAL_MACHINE\\SYSTEM\\ControlSet001\\Control\\Nls\\CustomLocale\\pl-PL; "
        "regkey: HKEY_LOCAL_MACHINE\\SYSTEM\\ControlSet001\\Control\\Nls\\ExtendedLocale\\pl-PL"
    )
    assert alert_named(alerts, "network_http")["tartarus"]["detection"]["match"] == (
        "url: http://www.msftconnecttest.com/connecttest.txt; "
        "url: http://ipv6.msftconnecttest.com/connecttest.txt"
    )


def test_an_alert_with_only_call_data_has_no_match_text(alerts: list[Event]) -> None:
    assert "detection" not in alert_named(alerts, "queries_locale_api")["tartarus"]


def test_repeated_match_text_is_listed_once_and_the_text_is_bounded(alerts: list[Event]) -> None:
    match = alert_named(alerts, "dllload_suspicious_directory")["tartarus"]["detection"]["match"]
    assert match.count("benign.exe loaded a DLL") == 1
    assert len(match) <= MATCH_LIMIT


# --- synthetic cases -----------------------------------------------------------------------


def signature(name: str, data: list[Any], **fields: Any) -> dict[str, Any]:
    return {"name": name, "description": f"{name} fired", "severity": 2, "data": data, **fields}


def report_with_signatures(*signatures: dict[str, Any], **extra: Any) -> dict[str, Any]:
    report = report_of(
        process(
            100,
            [
                call(
                    "NtWriteFile", id=7, category="filesystem", timestamp="2026-10-13 10:12:43,000"
                ),
                call(
                    "RegSetValueExW", id=8, category="registry", timestamp="2026-10-13 10:12:42,000"
                ),
            ],
        )
    )
    report["signatures"] = list(signatures)
    return report | extra


def ref(pid: int, cid: int) -> dict[str, Any]:
    return {"type": "call", "pid": pid, "cid": cid}


def test_a_reference_to_a_missing_call_or_process_is_dropped(context: IngestContext) -> None:
    report = report_with_signatures(
        signature("s", [ref(100, 7), ref(100, 99), ref(5, 7), ref(100, 7)])
    )
    [alert] = normalise(report, context)
    assert len(alert["related"]["events"]) == 1


@pytest.mark.parametrize(
    "data",
    [
        [{"type": "call", "pid": "x", "cid": 7}],
        [{"type": "call", "pid": 100}],
        [{"type": "call"}],
        [{"type": "call", "pid": None, "cid": None}],
        [None, 5, "call", []],
        "not a list",
    ],
)
def test_malformed_references_are_dropped_without_raising(
    data: Any, context: IngestContext
) -> None:
    [alert] = normalise(report_with_signatures(signature("s", data)), context)
    assert "related" not in alert


def test_references_given_as_text_numbers_still_resolve(context: IngestContext) -> None:
    text_ref = {"type": "call", "pid": "100", "cid": "0x7"}
    [alert] = normalise(report_with_signatures(signature("s", [text_ref])), context)
    assert len(alert["related"]["events"]) == 1


def test_the_earliest_referenced_call_sets_the_time_and_the_lane(context: IngestContext) -> None:
    later_first = signature("s", [ref(100, 7), ref(100, 8)])
    [alert] = normalise(report_with_signatures(later_first), context)
    assert alert["@timestamp"] == "2026-10-13T10:12:42.000Z"
    assert alert["tartarus"]["lane"] == "registry"
    assert alert["related"]["events"][0] != alert["related"]["events"][1]


def test_without_references_or_info_the_alert_takes_the_analysis_start(
    context: IngestContext,
) -> None:
    [alert] = normalise(report_with_signatures(signature("s", [])), context)
    assert alert["@timestamp"] == "2026-10-13T12:12:18.000Z"


def test_techniques_are_matched_by_signature_name_and_deduplicated(context: IngestContext) -> None:
    ttps = [
        {"signature": "s", "ttps": ["T1055", "T1027"]},
        {"signature": "s", "ttps": ["T1055", "T1564"]},
        {"signature": "orphan", "ttps": ["T9999"]},
        {"signature": "other", "ttps": []},
        None,
        {"signature": "s", "ttps": "T1"},
        {"signature": "s", "ttps": [["T2"], {"a": 1}, ""]},
        {"signature": 5, "ttps": ["T1"]},
    ]
    report = report_with_signatures(signature("s", []), signature("other", []), ttps=ttps)
    alerts = normalise(report, context)
    assert alerts[0]["threat"]["technique"]["id"] == ["T1055", "T1027", "T1564"]
    assert "threat" not in alerts[1]
    assert all("T9999" not in str(alert["threat"]) for alert in alerts if "threat" in alert)


def test_references_are_kept_when_the_signature_has_them(context: IngestContext) -> None:
    report = report_with_signatures(signature("s", [], references=["https://a.example", 5, ""]))
    [alert] = normalise(report, context)
    assert alert["rule"]["reference"] == ["https://a.example"]


def test_a_long_match_text_is_cut_at_the_limit(context: IngestContext) -> None:
    long_value = "x" * (MATCH_LIMIT * 3)
    [alert] = normalise(report_with_signatures(signature("s", [{"file": long_value}])), context)
    match = alert["tartarus"]["detection"]["match"]
    assert len(match) == MATCH_LIMIT
    assert match.endswith("…")


def test_structured_match_data_is_written_as_compact_json(context: IngestContext) -> None:
    data = [{"section": {"name": ".tls", "size": 1}}]
    [alert] = normalise(report_with_signatures(signature("s", data)), context)
    assert alert["tartarus"]["detection"]["match"] == 'section: {"name":".tls","size":1}'


@pytest.mark.parametrize("severity", [None, "x", True, -3])
def test_an_unreadable_severity_is_info(severity: Any, context: IngestContext) -> None:
    [alert] = normalise(report_with_signatures(signature("s", [], severity=severity)), context)
    assert alert["event"]["severity"] == 0


def test_a_signature_without_a_name_is_skipped(context: IngestContext) -> None:
    report = report_with_signatures({"description": "d", "data": []}, signature("kept", []))
    assert [a["rule"]["name"] for a in normalise(report, context)] == ["kept"]


def test_a_signature_without_a_description_is_summarised_by_its_name(
    context: IngestContext,
) -> None:
    [alert] = normalise(report_with_signatures({"name": "bare", "data": []}), context)
    assert alert["tartarus"]["summary"] == "bare"
    assert "description" not in alert["rule"]


def test_alerts_are_in_time_order_with_a_matching_sequence(
    alerts: list[Event], context: IngestContext
) -> None:
    stamps = [a["@timestamp"] for a in alerts]
    assert stamps == sorted(stamps)
    assert [a["event"]["sequence"] for a in alerts] == list(range(len(alerts)))


def test_the_alerts_do_not_change_the_report(
    full_report: dict[str, Any], context: IngestContext
) -> None:
    untouched = copy.deepcopy(full_report)
    normalise(full_report, context)
    assert full_report == untouched
