"""Flows to the fake local network are flagged by `cape-network`; the pcap stays their one row."""

from dataclasses import replace
from typing import Any

from app.ingest.cape_network import CapeNetworkNormalizer
from app.ingest.protocol import IngestContext
from tests.ingest.lan_sim_cases import DOMAIN_CONTROLLER, FILE_SERVER, GUEST, LAN_HOSTS, context_of
from tests.ingest.reports import report_of

Event = dict[str, Any]


def flow(destination: str, port: int, seconds: float = 1.0) -> dict[str, Any]:
    return {"src": GUEST, "sport": 50000, "dst": destination, "dport": port, "time": seconds}


def report_with_flows(*flows: dict[str, Any]) -> dict[str, Any]:
    report = report_of()
    report["network"] = {"tcp": list(flows), "udp": [flow("192.168.150.1", 53)]}
    return report


def flows_of(report: dict[str, Any], context: IngestContext) -> list[Event]:
    return list(CapeNetworkNormalizer().normalise(report, context))


def test_a_flow_to_a_fake_host_carries_the_hosts_lan_fields() -> None:
    report = report_with_flows(flow(FILE_SERVER, 445))

    [fake] = [
        e for e in flows_of(report, context_of(None)) if e["destination"]["ip"] == FILE_SERVER
    ]

    assert fake["tartarus"]["lan"] == {
        "simulated": True,
        "host": "fs01.corp.local",
        "role": "file-server",
        "preset": "small-office",
    }


def test_a_flow_to_any_other_address_is_not_flagged() -> None:
    events = flows_of(report_with_flows(flow(FILE_SERVER, 445)), context_of(None))

    [other] = [e for e in events if e["destination"]["ip"] == "192.168.150.1"]
    assert "lan" not in other["tartarus"]


def test_a_flow_is_flagged_whatever_the_port_the_host_does_not_serve() -> None:
    [probe] = flows_of(report_with_flows(flow(DOMAIN_CONTROLLER, 9999)), context_of(None))[:1]

    assert probe["tartarus"]["lan"]["host"] == "dc01.corp.local"


def test_without_fake_hosts_nothing_is_flagged_and_the_events_are_what_they_were() -> None:
    report = report_with_flows(flow(FILE_SERVER, 445), flow(DOMAIN_CONTROLLER, 389))
    off = context_of(None, lan_hosts={})

    flagged = flows_of(report, context_of(None))
    plain = flows_of(report, off)

    assert all("lan" not in e["tartarus"] for e in plain)
    assert [strip_lan(e) for e in flagged] == plain


def test_the_flow_count_does_not_depend_on_the_fake_hosts() -> None:
    report = report_with_flows(*(flow(address, 445, n) for n, address in enumerate(LAN_HOSTS)))

    assert len(flows_of(report, context_of(None))) == len(flows_of(report, context_of(None, {})))


def strip_lan(event: Event) -> Event:
    tartarus = {k: v for k, v in event["tartarus"].items() if k != "lan"}
    return {**event, "tartarus": tartarus}


def test_the_context_is_not_changed_by_flagging() -> None:
    context = context_of(None)

    flows_of(report_with_flows(flow(FILE_SERVER, 445)), context)

    assert replace(context) == context
