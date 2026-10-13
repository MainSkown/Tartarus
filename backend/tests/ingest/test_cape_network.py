import copy
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from app.ingest.cape_network import CapeNetworkNormalizer
from app.ingest.capemon import CapemonNormalizer
from app.ingest.ecs import event_id
from app.ingest.protocol import IngestContext
from tests.ingest.reports import call, process, report_of

Event = dict[str, Any]
STARTED = datetime(2026, 10, 13, 12, 12, 18, tzinfo=UTC)
EPOCH = STARTED.timestamp()


def normalise(report: dict[str, Any], context: IngestContext) -> list[Event]:
    return list(CapeNetworkNormalizer().normalise(report, context))


def of_action(events: list[Event], action: str) -> list[Event]:
    return [event for event in events if event["event"]["action"] == action]


@pytest.fixture
def events(full_report: dict[str, Any], context: IngestContext) -> list[Event]:
    return normalise(full_report, context)


def test_source_is_cape_network() -> None:
    assert CapeNetworkNormalizer().source == "cape-network"


# --- the real report -----------------------------------------------------------------------


def test_one_event_per_network_record(full_report: dict[str, Any], events: list[Event]) -> None:
    network = full_report["network"]
    assert len(of_action(events, "dns-query")) == len(network["dns"]) == 5
    assert len(of_action(events, "http-request")) == len(network["http"]) == 2
    flows = of_action(events, "network-connection")
    assert len(flows) == len(network["tcp"]) + len(network["udp"]) == 205
    assert len(events) == 212


def test_every_event_is_a_cape_network_event_in_the_network_lane(events: list[Event]) -> None:
    for event in events:
        assert event["event"]["module"] == "cape"
        assert event["event"]["dataset"] == "cape.network"
        assert event["event"]["kind"] == "event"
        assert event["event"]["category"] == ["network"]
        assert event["tartarus"]["lane"] == "network"


def test_ids_come_from_the_list_and_the_position_in_it(events: list[Event]) -> None:
    ids = {event["event"]["id"] for event in events}
    assert event_id(6, "cape-network", "dns", 0) in ids
    assert event_id(6, "cape-network", "dns", 4) in ids
    assert event_id(6, "cape-network", "tcp", 200) in ids
    assert event_id(6, "cape-network", "udp", 3) in ids
    assert event_id(6, "cape-network", "http", 1) in ids
    assert len(ids) == len(events)


def test_a_dns_query_carries_the_question_the_answers_and_the_epoch_time(
    events: list[Event],
) -> None:
    [first] = [e for e in events if e["event"]["id"] == event_id(6, "cape-network", "dns", 0)]
    assert first["@timestamp"] == "2026-10-13T12:12:26.015Z"
    assert first["dns"] == {
        "question": {"name": "www.msftconnecttest.com", "type": "A"},
        "answers": {"data": ["192.168.150.1"]},
    }
    assert first["related"]["ip"] == ["192.168.150.1"]
    assert first["network"]["protocol"] == "dns"
    assert first["tartarus"]["raw"]["request"] == "www.msftconnecttest.com"


def test_a_dns_query_without_answers_has_no_answer_fields(events: list[Event]) -> None:
    [unanswered] = [e for e in events if e["event"]["id"] == event_id(6, "cape-network", "dns", 2)]
    assert unanswered["dns"] == {"question": {"name": "outlook.office.com", "type": "A"}}
    assert "related" not in unanswered or "ip" not in unanswered["related"]


def test_a_tcp_flow_is_placed_by_its_relative_time_after_the_analysis_start(
    events: list[Event],
) -> None:
    [flow] = [e for e in events if e["event"]["id"] == event_id(6, "cape-network", "tcp", 1)]
    assert flow["@timestamp"] == "2026-10-13T12:12:19.745Z"
    assert flow["source"] == {"ip": "192.168.150.10", "port": 65522}
    assert flow["destination"] == {"ip": "192.168.150.1", "port": 443}
    assert flow["network"] == {"transport": "tcp"}
    assert flow["event"]["type"] == ["connection"]


def test_a_udp_flow_names_its_transport(events: list[Event]) -> None:
    [flow] = [e for e in events if e["event"]["id"] == event_id(6, "cape-network", "udp", 0)]
    assert flow["network"] == {"transport": "udp"}
    assert flow["destination"] == {"ip": "192.168.150.1", "port": 53}


def test_an_http_request_carries_method_url_agent_and_host(events: list[Event]) -> None:
    [request] = [e for e in events if e["event"]["id"] == event_id(6, "cape-network", "http", 0)]
    assert request["@timestamp"] == "2026-10-13T12:12:26.022Z"
    assert request["http"] == {"request": {"method": "GET"}}
    assert request["url"] == {"full": "http://www.msftconnecttest.com/connecttest.txt"}
    assert request["user_agent"] == {"original": "Microsoft NCSI"}
    assert request["destination"] == {"domain": "www.msftconnecttest.com", "port": 80}
    assert request["network"] == {"transport": "tcp", "protocol": "http"}


def test_events_are_in_time_order_with_a_matching_sequence(events: list[Event]) -> None:
    timestamps = [event["@timestamp"] for event in events]
    assert timestamps == sorted(timestamps)
    assert [e["event"]["sequence"] for e in events] == list(range(len(events)))


def test_every_event_falls_inside_the_analysis_window(
    full_report: dict[str, Any], events: list[Event]
) -> None:
    start = STARTED - timedelta(seconds=5)
    end = datetime(2026, 10, 13, 12, 13, 13, tzinfo=UTC) + timedelta(seconds=60)
    assert full_report["info"]["started"] == "2026-10-13 12:12:18"
    for event in events:
        assert start <= datetime.fromisoformat(event["@timestamp"]) <= end, event["@timestamp"]


def test_domains_and_hosts_add_no_events(
    full_report: dict[str, Any], context: IngestContext
) -> None:
    without = copy.deepcopy(full_report)
    without["network"]["domains"] = []
    without["network"]["hosts"] = []
    assert normalise(without, context) == normalise(full_report, context)


def test_the_dns_query_the_sample_made_is_attributed_to_the_process_that_resolved_it(
    events: list[Event],
) -> None:
    attributed = [e for e in events if "process" in e]
    [query] = attributed
    assert query["dns"]["question"]["name"] == "tartarus-selftest.example"
    assert query["process"]["pid"] == 10116
    assert query["process"]["name"] == "benign.exe"
    assert query["process"]["entity_id"] == "6:10116@2026-10-13T12:12:41.164Z"
    assert "thread" not in query["process"]


def test_an_attributed_event_links_to_the_capemon_event_that_justified_it(
    full_report: dict[str, Any], context: IngestContext, events: list[Event]
) -> None:
    capemon = list(CapemonNormalizer().normalise(full_report, context))
    [resolved] = [e for e in capemon if e["event"]["action"] == "dns-query"]
    [query] = [e for e in events if "process" in e]
    assert query["related"]["events"] == [resolved["event"]["id"]]


# --- attribution only on an exact match -----------------------------------------------------


def network_report(*processes: dict[str, Any], **network: Any) -> dict[str, Any]:
    report = report_of(*processes)
    report["network"] = network
    return report


def resolver(pid: int, name: str, api: str = "getaddrinfo", argument: str = "NodeName") -> Any:
    return process(pid, [call(api, {argument: name})], name=f"p{pid}.exe")


def dns_record(name: str) -> dict[str, Any]:
    return {"request": name, "type": "A", "answers": [], "first_seen": EPOCH + 5}


def flow(ip: str, port: int) -> dict[str, Any]:
    return {"src": "10.0.0.2", "sport": 50000, "dst": ip, "dport": port, "offset": 1, "time": 1.0}


def attributed_pids(events: list[Event]) -> list[int | None]:
    return [event.get("process", {}).get("pid") for event in events]


@pytest.mark.parametrize(
    ("api", "argument"), [("GetAddrInfoW", "NodeName"), ("DnsQuery_W", "Name")]
)
def test_a_dns_query_is_attributed_on_an_exact_name(
    api: str, argument: str, context: IngestContext
) -> None:
    report = network_report(
        resolver(7, "evil.example", api, argument), dns=[dns_record("evil.example")]
    )
    assert attributed_pids(normalise(report, context)) == [7]


def test_a_dns_name_matches_regardless_of_case_and_the_trailing_dot(
    context: IngestContext,
) -> None:
    report = network_report(resolver(7, "Evil.Example"), dns=[dns_record("evil.example.")])
    assert attributed_pids(normalise(report, context)) == [7]


@pytest.mark.parametrize("queried", ["evil.example.com", "xevil.example", "example", "evil"])
def test_a_dns_name_that_only_resembles_the_resolved_one_is_not_attributed(
    queried: str, context: IngestContext
) -> None:
    report = network_report(resolver(7, "evil.example"), dns=[dns_record(queried)])
    assert attributed_pids(normalise(report, context)) == [None]


def test_a_name_resolved_by_two_processes_is_attributed_to_neither(context: IngestContext) -> None:
    report = network_report(
        resolver(7, "evil.example"), resolver(8, "evil.example"), dns=[dns_record("evil.example")]
    )
    assert attributed_pids(normalise(report, context)) == [None]


def test_a_name_resolved_twice_by_one_process_is_still_that_process(context: IngestContext) -> None:
    twice = process(
        7,
        [call("getaddrinfo", {"NodeName": "evil.example"}, id=number) for number in (1, 2)],
    )
    report = network_report(twice, dns=[dns_record("evil.example")])
    assert attributed_pids(normalise(report, context)) == [7]


def test_a_flow_is_attributed_on_an_exact_destination_address_and_port(
    context: IngestContext,
) -> None:
    connecting = process(7, [call("connect", {"ip": "203.0.113.9", "port": "443"})])
    report = network_report(
        connecting,
        tcp=[flow("203.0.113.9", 443), flow("203.0.113.9", 80), flow("203.0.113.10", 443)],
    )
    assert attributed_pids(normalise(report, context)) == [7, None, None]


def test_an_endpoint_two_processes_connected_to_is_attributed_to_neither(
    context: IngestContext,
) -> None:
    arguments = {"ip": "203.0.113.9", "port": "443"}
    report = network_report(
        process(7, [call("connect", arguments)]),
        process(8, [call("connect", arguments)]),
        tcp=[flow("203.0.113.9", 443)],
    )
    assert attributed_pids(normalise(report, context)) == [None]


def test_an_http_request_is_attributed_on_an_exact_url(context: IngestContext) -> None:
    opening = process(7, [call("InternetOpenUrlW", {"URL": "http://evil.example/a.exe"})])
    request = {
        "host": "evil.example",
        "port": 80,
        "uri": "http://evil.example/a.exe",
        "method": "GET",
    }
    other = {**request, "uri": "http://evil.example/b.exe"}
    report = network_report(opening, http=[request, other])
    assert attributed_pids(normalise(report, context)) == [7, None]


def test_a_report_without_capemon_processes_attributes_nothing(context: IngestContext) -> None:
    report = {"network": {"dns": [dns_record("evil.example")], "tcp": [flow("203.0.113.9", 443)]}}
    assert attributed_pids(normalise(report, context)) == [None, None]


# --- time fallbacks and damaged records ----------------------------------------------------


def test_a_dns_record_without_a_time_takes_the_analysis_start(context: IngestContext) -> None:
    [event] = normalise(network_report(dns=[{"request": "a.example"}]), context)
    assert event["@timestamp"] == "2026-10-13T12:12:18.000Z"


def test_an_http_request_without_a_time_takes_the_time_of_the_dns_query_for_its_host(
    context: IngestContext,
) -> None:
    request = {"host": "A.Example", "port": 80, "uri": "http://a.example/x", "method": "GET"}
    report = network_report(
        dns=[{**dns_record("a.example"), "first_seen": EPOCH + 9}], http=[request]
    )
    [_, http] = normalise(report, context)
    assert http["@timestamp"] == "2026-10-13T12:12:27.000Z"


def test_an_http_request_without_a_time_or_a_dns_query_takes_the_analysis_start(
    context: IngestContext,
) -> None:
    request = {"host": "a.example", "port": 80, "uri": "http://a.example/x", "method": "GET"}
    [event] = normalise(network_report(http=[request]), context)
    assert event["@timestamp"] == "2026-10-13T12:12:18.000Z"


def test_a_flow_without_a_time_takes_the_analysis_start(context: IngestContext) -> None:
    broken = {**flow("203.0.113.9", 443), "time": "soon"}
    [event] = normalise(network_report(tcp=[broken]), context)
    assert event["@timestamp"] == "2026-10-13T12:12:18.000Z"


@pytest.mark.parametrize(
    "network",
    [
        {"dns": [None, 3, {}, {"request": ""}, {"request": 5}]},
        {"tcp": [None, "x", {}, {"dst": "1.2.3.4"}, {"dport": 80}, {"dst": "", "dport": 1}]},
        {"udp": [{"dst": "1.2.3.4", "dport": "many"}]},
        {"http": [None, {}, {"host": "a"}, {"uri": 4}]},
        {"dns": "x", "tcp": 3, "udp": None, "http": {"a": 1}},
    ],
)
def test_damaged_records_are_skipped_without_raising(
    network: dict[str, Any], context: IngestContext
) -> None:
    events = normalise({"network": network}, context)
    assert all(event["tartarus"]["lane"] == "network" for event in events)


def test_a_flow_with_an_address_but_no_port_keeps_the_address(context: IngestContext) -> None:
    [event] = normalise(network_report(tcp=[{"dst": "1.2.3.4", "time": 1}]), context)
    assert event["destination"] == {"ip": "1.2.3.4"}


def test_the_network_normaliser_leaves_the_report_alone(
    full_report: dict[str, Any], context: IngestContext
) -> None:
    untouched = copy.deepcopy(full_report)
    normalise(full_report, context)
    assert full_report == untouched
