"""A connection to a fake host is flagged and counted whichever source saw it.

Sysmon's EID 3, capemon's `connect` and the pcap's flow are three views of one connection: each
carries `tartarus.lan`, `summary.lan` counts the connection once, and a Sigma connection rule
raises one alert. Run through the ingester, so the claims hold on the real pipeline. Route `none`
leaves no pcap, and a bare connect (no payload) is no pcap flow, so Sysmon and capemon must be
enough on their own.
"""

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from app.analyses.lan_models import LanSummary
from app.ingest.ingester import ReportIngester
from app.ingest.lan_fields import lan_section
from app.ingest.protocol import LanHost
from app.rules.loader import load_rules
from app.views.network import shape_network
from tests.ingest.conftest import ANALYSIS_ID
from tests.ingest.fake_index import FakeIndex
from tests.ingest.lan_sim_cases import FILE_SERVER, GUEST, LAN_HOSTS
from tests.ingest.reports import call
from tests.ingest.sysmon_cases import analysis_with, event_xml, guid, monitored, report_with
from tests.rules.support import TARTARUS_RULESET

Event = dict[str, Any]

SAMPLE = r"C:\Users\Megan\AppData\Local\Temp\sample.exe"
SAMPLE_PID = 700
SAMPLE_GUID = guid(10)
SAMPLE_FIRST_SEEN = "2026-10-18 20:43:49,000"
ACTION_UTC = "2026-10-18 20:43:50"
ACTION_TIME = f"{ACTION_UTC}.000"
PRINTER = "192.168.150.205"
OUTSIDE = "192.168.150.99"
RDP, SMB = 3389, 445


def eid3(record_id: int, destination: str, port: int, source_port: int) -> str:
    return event_xml(
        3,
        record_id,
        ACTION_TIME,
        {
            "UtcTime": ACTION_TIME,
            "ProcessGuid": SAMPLE_GUID,
            "ProcessId": SAMPLE_PID,
            "Image": SAMPLE,
            "Protocol": "tcp",
            "Initiated": "true",
            "SourceIp": GUEST,
            "SourcePort": source_port,
            "DestinationIp": destination,
            "DestinationPort": port,
        },
    )


def connect(destination: str, port: int) -> Event:
    return call("connect", {"ip": destination, "port": str(port)}, timestamp=f"{ACTION_UTC},000")


def pcap_flow(destination: str, port: int, source_port: int) -> Event:
    return {"src": GUEST, "sport": source_port, "dst": destination, "dport": port, "time": 20.5}


async def ingest(  # noqa: PLR0913 - the sources of a run, each a thing a test varies
    tmp_path: Path,
    *,
    capemon: Sequence[Event] = (),
    sysmon: Sequence[str] = (),
    pcap: list[Event] | None = None,
    lan_hosts: dict[str, LanHost] | None = None,
    rules: bool = False,
) -> tuple[FakeIndex, LanSummary | None]:
    report = report_with(
        monitored(SAMPLE_PID, SAMPLE, first_seen=SAMPLE_FIRST_SEEN, calls=list(capemon))
    )
    if pcap is not None:
        report["network"] = {"tcp": pcap}
    report_path = tmp_path / "reports" / "report.json"
    report_path.parent.mkdir(parents=True)
    report_path.write_text(json.dumps(report), encoding="utf-8")
    if sysmon:
        analysis_with(tmp_path, *sysmon)
    index = FakeIndex()
    ingester = ReportIngester(
        index, rules=(lambda: load_rules(TARTARUS_RULESET)) if rules else (lambda: [])
    )
    result = await ingester.ingest(
        ANALYSIS_ID, report_path, lan_hosts=LAN_HOSTS if lan_hosts is None else lan_hosts
    )
    return index, result.lan


def of_dataset(index: FakeIndex, dataset: str, action: str = "network-connection") -> list[Event]:
    return [
        e
        for e in index.events
        if e["event"]["action"] == action and e["event"]["dataset"] == dataset
    ]


def alerts(index: FakeIndex) -> list[Event]:
    return [e for e in index.events if e["event"]["kind"] == "alert"]


def attempts_of(summary: LanSummary | None, address: str, port: int) -> int:
    assert summary is not None
    [host] = [h for h in summary.hosts if h.address == address]
    return sum(use.attempts for use in host.services if use.port == port)


# --- the flag ------------------------------------------------------------------------------------


async def test_a_sysmon_connection_to_a_fake_host_carries_the_hosts_lan_fields(
    tmp_path: Path,
) -> None:
    index, _ = await ingest(tmp_path, sysmon=[eid3(1, FILE_SERVER, SMB, 50001)])

    [event] = of_dataset(index, "sysmon.evtx")

    assert event["tartarus"]["lan"] == lan_section(LAN_HOSTS[FILE_SERVER])["lan"]


async def test_a_capemon_connection_to_a_fake_host_carries_the_hosts_lan_fields(
    tmp_path: Path,
) -> None:
    index, _ = await ingest(tmp_path, capemon=[connect(FILE_SERVER, SMB)])

    [event] = of_dataset(index, "capemon.derived")

    assert event["tartarus"]["lan"] == lan_section(LAN_HOSTS[FILE_SERVER])["lan"]


async def test_a_connection_to_any_other_address_is_not_flagged(tmp_path: Path) -> None:
    index, _ = await ingest(
        tmp_path,
        capemon=[connect(OUTSIDE, SMB)],
        sysmon=[eid3(1, OUTSIDE, SMB, 50001)],
        pcap=[pcap_flow(OUTSIDE, SMB, 50001)],
    )

    connections = [e for e in index.events if e["event"]["action"] == "network-connection"]
    assert len(connections) == 3
    assert all("lan" not in e["tartarus"] for e in connections)


async def test_without_the_fake_lan_no_connection_is_flagged_and_there_is_no_summary(
    tmp_path: Path,
) -> None:
    index, summary = await ingest(
        tmp_path,
        capemon=[connect(FILE_SERVER, SMB)],
        sysmon=[eid3(1, FILE_SERVER, SMB, 50001)],
        lan_hosts={},
    )

    assert all("lan" not in e["tartarus"] for e in index.events)
    assert summary is None


async def test_the_pcap_flow_keeps_its_flag_with_the_other_sources_present(
    tmp_path: Path,
) -> None:
    index, _ = await ingest(
        tmp_path,
        capemon=[connect(FILE_SERVER, SMB)],
        sysmon=[eid3(1, FILE_SERVER, SMB, 50001)],
        pcap=[pcap_flow(FILE_SERVER, SMB, 50001)],
    )

    flows = [of_dataset(index, d) for d in ("cape.network", "sysmon.evtx", "capemon.derived")]

    assert [len(found) for found in flows] == [1, 1, 1]
    assert {json.dumps(found[0]["tartarus"]["lan"], sort_keys=True) for found in flows} == {
        json.dumps(lan_section(LAN_HOSTS[FILE_SERVER])["lan"], sort_keys=True)
    }


# --- summary.lan counts a connection once --------------------------------------------------------


async def test_a_connection_all_three_sources_saw_is_one_attempt(tmp_path: Path) -> None:
    _, summary = await ingest(
        tmp_path,
        capemon=[connect(FILE_SERVER, SMB)],
        sysmon=[eid3(1, FILE_SERVER, SMB, 50001)],
        pcap=[pcap_flow(FILE_SERVER, SMB, 50001)],
    )

    assert summary is not None
    assert summary.totals.attempts == 1
    assert attempts_of(summary, FILE_SERVER, SMB) == 1


async def test_a_bare_connect_only_sysmon_and_capemon_saw_is_listed_with_its_attempt(
    tmp_path: Path,
) -> None:
    _, summary = await ingest(
        tmp_path,
        capemon=[connect(PRINTER, RDP)],
        sysmon=[eid3(1, PRINTER, RDP, 50002)],
        pcap=[],
    )

    assert summary is not None
    assert [h.address for h in summary.hosts] == [PRINTER]
    assert summary.hosts[0].services[0].service == "rdp"
    assert summary.totals.attempts == 1


async def test_sysmon_alone_is_an_attempt_and_so_is_capemon_alone(tmp_path: Path) -> None:
    _, by_sysmon = await ingest(tmp_path / "a", sysmon=[eid3(1, PRINTER, RDP, 50002)])
    _, by_capemon = await ingest(tmp_path / "b", capemon=[connect(PRINTER, RDP)])

    assert attempts_of(by_sysmon, PRINTER, RDP) == 1
    assert attempts_of(by_capemon, PRINTER, RDP) == 1


async def test_two_connections_to_one_port_are_two_attempts(tmp_path: Path) -> None:
    _, summary = await ingest(
        tmp_path,
        sysmon=[eid3(1, PRINTER, RDP, 50002), eid3(2, PRINTER, RDP, 50003)],
        pcap=[pcap_flow(PRINTER, RDP, 50002)],
    )

    assert attempts_of(summary, PRINTER, RDP) == 2


async def test_a_pcap_flow_and_a_bare_connect_to_other_ports_are_each_an_attempt(
    tmp_path: Path,
) -> None:
    _, summary = await ingest(
        tmp_path,
        sysmon=[eid3(1, FILE_SERVER, SMB, 50001), eid3(2, FILE_SERVER, RDP, 50002)],
        pcap=[pcap_flow(FILE_SERVER, SMB, 50001)],
    )

    assert attempts_of(summary, FILE_SERVER, SMB) == 1
    assert attempts_of(summary, FILE_SERVER, RDP) == 1
    assert summary is not None
    assert summary.totals.attempts == 2


# --- route none: no pcap at all ------------------------------------------------------------------


async def test_without_a_pcap_the_network_view_flags_the_fake_hosts_and_flows(
    tmp_path: Path,
) -> None:
    index, summary = await ingest(
        tmp_path,
        capemon=[connect(PRINTER, RDP), connect(OUTSIDE, RDP)],
        sysmon=[eid3(1, PRINTER, RDP, 50002), eid3(2, OUTSIDE, RDP, 50003)],
    )

    view = shape_network(index.events, simulated=True, limit=100)

    assert {flow.destination_ip: flow.simulated for flow in view.flows.items} == {
        PRINTER: True,
        OUTSIDE: False,
    }
    hosts = {host.host: host for host in view.hosts.items}
    assert (hosts[PRINTER].simulated, hosts[PRINTER].lan_host) == (True, "ws205.corp.local")
    assert hosts[OUTSIDE].simulated is False
    assert summary is not None
    assert [h.address for h in summary.hosts] == [PRINTER]


# --- the connection rules ------------------------------------------------------------------------


async def test_a_bare_rdp_connect_seen_by_sysmon_raises_the_rdp_rule(tmp_path: Path) -> None:
    index, _ = await ingest(tmp_path, sysmon=[eid3(1, PRINTER, RDP, 50002)], pcap=[], rules=True)

    [alert] = alerts(index)

    assert alert["rule"]["name"] == "Process Connects To A Fake LAN Host Over RDP"
    assert alert["process"]["name"] == "sample.exe"


async def test_one_connection_in_three_sources_raises_one_alert_repeated(tmp_path: Path) -> None:
    index, _ = await ingest(
        tmp_path,
        capemon=[connect(PRINTER, RDP)],
        sysmon=[eid3(1, PRINTER, RDP, 50002)],
        pcap=[pcap_flow(PRINTER, RDP, 50002)],
        rules=True,
    )

    [alert] = alerts(index)

    assert alert["tartarus"]["detection"]["repeated"] == 2


async def test_a_connection_to_an_address_outside_the_preset_raises_no_alert(
    tmp_path: Path,
) -> None:
    index, _ = await ingest(
        tmp_path,
        capemon=[connect(OUTSIDE, RDP)],
        sysmon=[eid3(1, OUTSIDE, RDP, 50002)],
        rules=True,
    )

    assert alerts(index) == []


# --- the derived events stay what they were ------------------------------------------------------


async def test_a_sweep_is_one_event_whatever_sources_flagged_the_connects(
    tmp_path: Path,
) -> None:
    addresses = [a for a, host in LAN_HOSTS.items() if host.role == "workstation"][:5]
    index, _ = await ingest(
        tmp_path,
        capemon=[connect(a, RDP) for a in addresses],
        sysmon=[eid3(n, a, RDP, 50000 + n) for n, a in enumerate(addresses)],
    )

    [sweep] = [e for e in index.events if e["event"]["action"] == "lan-sweep"]

    assert sweep["tartarus"]["lan"]["count"] == 5
    assert len(sweep["related"]["events"]) == 5
