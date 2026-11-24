"""`summary.lan` from the events a final ingest built: what counts, caps and hostile strings."""

import json
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path
from typing import Any

from app.analyses.lan_models import LanSummary
from app.analyses.lan_summary import MAX_FILES_PER_HOST, MAX_TEXT, lan_summary
from app.ingest.cape_network import CapeNetworkNormalizer
from app.ingest.lan_sim import LanSimNormalizer
from app.ingest.protocol import LanHost
from tests.ingest.lan_sim_cases import (
    DOMAIN_CONTROLLER,
    FILE_SERVER,
    LAN_HOSTS,
    PRESET,
    STARTED,
    aggregate,
    at,
    context_of,
    file_write,
    login,
    record,
    service_request,
    share_access,
    write_log,
)

Event = dict[str, Any]


def tcp_flow(address: str, port: int, seconds: float) -> dict[str, Any]:
    return {"src": "192.168.150.10", "sport": 50000, "dst": address, "dport": port, "time": seconds}


def events_of(
    tmp_path: Path,
    records: list[Any],
    flows: list[dict[str, Any]] | None = None,
    hosts: Mapping[str, LanHost] | None = None,
) -> list[Event]:
    """What the ingest streams for the fake LAN: the daemon's log and the pcap's flows."""
    write_log(tmp_path, records)
    context = context_of(tmp_path, hosts)
    report = {"network": {"tcp": flows or []}}
    return [
        *CapeNetworkNormalizer().normalise(report, context),
        *LanSimNormalizer().normalise(report, context),
    ]


def summarise(
    tmp_path: Path, records: list[Any], flows: list[dict[str, Any]] | None = None, **options: Any
) -> LanSummary:
    summary = lan_summary(events_of(tmp_path, records, flows), LAN_HOSTS, **options)
    assert summary is not None
    return summary


def host_of(summary: LanSummary, fqdn: str) -> Any:
    return next(host for host in summary.hosts if host.fqdn == fqdn)


def test_a_run_that_did_not_ask_for_the_fake_lan_has_no_summary(tmp_path: Path) -> None:
    events = events_of(tmp_path, [login()])

    assert lan_summary(events, {}) is None


def test_a_run_that_did_nothing_on_the_lan_has_a_summary_without_hosts(tmp_path: Path) -> None:
    summary = summarise(tmp_path, [])

    assert summary.hosts == []
    assert (summary.totals.hosts, summary.totals.attempts) == (0, 0)
    assert (summary.totals.credentials, summary.totals.files) == (0, 0)
    assert summary.truncated is False


def test_the_summary_names_the_preset_by_id_and_name() -> None:
    named = {a: replace(host, preset_name="Small office") for a, host in LAN_HOSTS.items()}

    summary = lan_summary([], named)

    assert summary is not None
    assert (summary.preset.id, summary.preset.name) == (PRESET, "Small office")


def test_the_preset_name_falls_back_to_its_id() -> None:
    summary = lan_summary([], LAN_HOSTS)

    assert summary is not None
    assert summary.preset.name == PRESET


def test_only_the_hosts_the_sample_touched_are_listed(tmp_path: Path) -> None:
    summary = summarise(tmp_path, [login()])

    assert [host.fqdn for host in summary.hosts] == ["fs01.corp.local"]
    host = summary.hosts[0]
    assert (host.address, host.role) == (FILE_SERVER, "file-server")
    assert summary.totals.hosts == 1


def test_a_host_lists_the_services_touched_with_their_attempts_and_times(tmp_path: Path) -> None:
    records = [
        login(seconds=2),
        share_access(seconds=3),
        service_request(seconds=5),
        record("service-request", seconds=4, service="rdp", port=3389, name="x509", detail=""),
    ]

    host = summarise(tmp_path, records).hosts[0]

    smb, rdp = host.services
    assert (smb.service, smb.port, smb.attempts) == ("smb", 445, 3)
    assert (smb.first, smb.last) == (at(2), at(5))
    assert (rdp.service, rdp.port, rdp.attempts) == ("rdp", 3389, 1)
    assert (rdp.first, rdp.last) == (at(4), at(4))
    assert (host.first, host.last) == (at(2), at(5))


def test_an_attempt_is_a_login_a_share_access_a_service_request_or_a_connection_flow(
    tmp_path: Path,
) -> None:
    records = [login(), share_access(), service_request(), file_write()]

    summary = summarise(tmp_path, records, [tcp_flow(FILE_SERVER, 3389, 1)])

    assert [(s.port, s.attempts) for s in summary.hosts[0].services] == [(445, 3), (3389, 1)]
    assert summary.totals.attempts == 4


def test_a_flow_to_a_port_the_daemon_logged_events_on_is_not_counted_again(tmp_path: Path) -> None:
    records = [login(), share_access()]

    summary = summarise(tmp_path, records, [tcp_flow(FILE_SERVER, 445, 1)])

    assert summary.hosts[0].services[0].attempts == 2
    assert summary.totals.attempts == 2


def test_a_flow_is_still_counted_when_the_daemon_logged_on_another_host_or_port(
    tmp_path: Path,
) -> None:
    records = [login(host="dc01.corp.local")]
    flows = [tcp_flow(FILE_SERVER, 445, 1), tcp_flow(DOMAIN_CONTROLLER, 389, 2)]

    summary = summarise(tmp_path, records, flows)

    assert summary.totals.attempts == 3


def test_a_flow_to_a_port_a_flood_was_counted_on_is_not_counted_again(tmp_path: Path) -> None:
    summary = summarise(tmp_path, [aggregate(count=100)], [tcp_flow(FILE_SERVER, 445, 1)])

    assert summary.totals.attempts == 100


def test_a_scan_that_only_connected_counts_by_its_flows(tmp_path: Path) -> None:
    flows = [tcp_flow(DOMAIN_CONTROLLER, 445, 1), tcp_flow(DOMAIN_CONTROLLER, 22, 2)]

    summary = summarise(tmp_path, [], flows)

    host = summary.hosts[0]
    assert host.fqdn == "dc01.corp.local"
    assert [(s.service, s.port, s.attempts) for s in host.services] == [
        (None, 22, 1),
        ("smb", 445, 1),
    ]


def test_a_flow_to_an_address_outside_the_preset_is_not_a_lan_attempt(tmp_path: Path) -> None:
    summary = summarise(tmp_path, [], [tcp_flow("192.168.150.1", 445, 1)])

    assert summary.hosts == []


def test_the_derived_events_are_not_counted_again(tmp_path: Path) -> None:
    flows = [tcp_flow(address, 445, n) for n, address in enumerate(LAN_HOSTS)]
    events = events_of(tmp_path, [], flows)
    assert any(e["event"]["dataset"] == "lan-sim.derived" for e in events)

    summary = lan_summary(events, LAN_HOSTS)

    assert summary is not None
    assert summary.totals.attempts == len(flows)


def test_the_same_credential_is_one_entry_with_its_count_and_whether_any_attempt_won(
    tmp_path: Path,
) -> None:
    records = [
        login(seconds=1, secret="Password1", success=False),  # noqa: S106 -- test data
        login(seconds=2, secret="Winter2026", success=True),  # noqa: S106 -- test data
        login(seconds=3, user="root", domain="", mechanism="password", secret="toor"),  # noqa: S106 -- test data
    ]

    credentials = summarise(tmp_path, records).hosts[0].credentials

    admin, root = credentials
    assert (admin.user, admin.domain, admin.mechanism) == ("Administrator", "CORP", "ntlm")
    assert (admin.count, admin.success, admin.secret_as_sent) == (2, True, "Password1")
    assert (root.user, root.domain, root.mechanism) == ("root", "", "password")
    assert (root.count, root.success) == (1, False)


def test_a_login_without_a_secret_has_none(tmp_path: Path) -> None:
    credential = summarise(tmp_path, [login(secret="")]).hosts[0].credentials[0]

    assert credential.secret_as_sent is None


def test_a_secret_is_capped(tmp_path: Path) -> None:
    credential = summarise(tmp_path, [login(secret="p" * 10_000)]).hosts[0].credentials[0]

    assert credential.secret_as_sent is not None
    assert len(credential.secret_as_sent) <= MAX_TEXT


def test_the_credentials_count_in_the_totals_across_hosts(tmp_path: Path) -> None:
    records = [login(), login(host="dc01.corp.local", service="smb"), login(user="other")]

    summary = summarise(tmp_path, records)

    assert summary.totals.credentials == 3


def test_the_files_written_are_listed_with_their_share_size_and_hash(tmp_path: Path) -> None:
    records = [file_write(path="\\a.exe", size=10), file_write(path="\\b.dll", sha256=None)]

    host = summarise(tmp_path, records).hosts[0]

    first, second = host.files
    assert (first.path, first.share, first.size, first.sha256) == (
        "\\a.exe",
        "ADMIN$",
        10,
        "ab" * 32,
    )
    assert second.sha256 is None
    assert host.files_more == 0


def test_the_files_are_capped_and_the_rest_counted(tmp_path: Path) -> None:
    records = [file_write(path=f"\\f{n}.bin", seconds=n) for n in range(MAX_FILES_PER_HOST + 7)]

    summary = summarise(tmp_path, records)

    host = summary.hosts[0]
    assert len(host.files) == MAX_FILES_PER_HOST
    assert host.files_more == 7
    assert summary.totals.files == MAX_FILES_PER_HOST + 7


def test_a_truncated_daemon_log_is_said(tmp_path: Path) -> None:
    summary = summarise(tmp_path, [login()], log_truncated=True)

    assert summary.truncated is True


def test_a_flood_aggregate_adds_its_count_its_users_and_its_secrets(tmp_path: Path) -> None:
    records = [
        login(user="Administrator"),
        aggregate(count=9800, users=["admin", "root"], secrets=["Spring2026"]),
    ]

    summary = summarise(tmp_path, records)

    host = summary.hosts[0]
    assert host.services[0].attempts == 9801
    assert summary.totals.attempts == 9801
    by_user = {c.user: c for c in host.credentials}
    assert {"Administrator", "admin", "root"} <= set(by_user)
    assert by_user["admin"].count == 0
    assert by_user[""].secret_as_sent == "Spring2026"  # noqa: S105 -- test data


def test_an_aggregate_user_already_seen_does_not_add_a_second_entry(tmp_path: Path) -> None:
    records = [aggregate(users=["Administrator"], secrets=[]), login(user="Administrator")]

    credentials = summarise(tmp_path, records).hosts[0].credentials

    assert [c.user for c in credentials] == ["Administrator"]


def test_an_aggregate_service_with_a_known_port_lands_on_that_service(tmp_path: Path) -> None:
    summary = summarise(tmp_path, [aggregate(service="smb")])

    assert [(s.service, s.port) for s in summary.hosts[0].services] == [("smb", 445)]


def test_the_hosts_come_in_the_order_the_sample_first_touched_them(tmp_path: Path) -> None:
    records = [
        login(seconds=9, host="fs01.corp.local"),
        login(seconds=1, host="dc01.corp.local"),
    ]

    summary = summarise(tmp_path, records)

    assert [host.fqdn for host in summary.hosts] == ["dc01.corp.local", "fs01.corp.local"]


# --- hostile strings ---------------------------------------------------------------------------


def hostile_event(**changes: Any) -> Event:
    """A login the way the normaliser would build it, but with strings it never cut."""
    event: Event = {
        "@timestamp": STARTED.isoformat(),
        "event": {"action": "lan-login-attempt", "dataset": "lan-sim.log", "outcome": "failure"},
        "destination": {"ip": FILE_SERVER, "port": 445},
        "user": {"name": "<script>alert(1)</script>" + "u" * 5000, "domain": "D\x00\x1b" * 500},
        "tartarus": {
            "lan": {
                "simulated": True,
                "host": "fs01.corp.local",
                "service": "smb",
                "mechanism": "ntlm" * 500,
                "credential": "\u202e" + "s" * 5000,
            }
        },
    }
    return event | changes


def test_every_string_is_cleaned_and_capped_again_whatever_the_event_says() -> None:
    summary = lan_summary([hostile_event()], LAN_HOSTS)

    assert summary is not None
    credential = summary.hosts[0].credentials[0]
    assert credential.user.startswith("<script>")
    for text in (credential.user, credential.domain, credential.mechanism):
        assert len(text) <= MAX_TEXT
    assert "\x00" not in credential.domain
    assert credential.secret_as_sent is not None
    assert credential.secret_as_sent.startswith("s")


def test_a_file_path_from_an_event_is_capped() -> None:
    event = hostile_event(
        event={"action": "lan-file-write", "dataset": "lan-sim.log"},
        file={"path": "\\" + "p" * 50_000, "size": 3},
    )
    event["tartarus"]["lan"]["share"] = "S" * 5000

    summary = lan_summary([event], LAN_HOSTS)

    assert summary is not None
    written = summary.hosts[0].files[0]
    assert len(written.path) <= 1024
    assert len(written.share) <= MAX_TEXT


def test_an_event_missing_a_field_is_skipped_not_raised_on() -> None:
    broken: Event = {"@timestamp": STARTED.isoformat(), "event": {"action": "lan-login-attempt"}}

    assert lan_summary([broken, hostile_event(destination={})], LAN_HOSTS) is not None


def test_the_summary_survives_a_round_trip_through_json(tmp_path: Path) -> None:
    summary = summarise(tmp_path, [login(), file_write()], [tcp_flow(FILE_SERVER, 445, 1)])

    stored = json.loads(json.dumps(summary.model_dump(mode="json")))

    assert LanSummary.model_validate(stored) == summary


# --- one connection seen by several sources is one attempt ---------------------------------------


def connection(
    dataset: str, address: str, port: int, source_port: int | None, seconds: float
) -> Event:
    """A flagged `network-connection` as the pcap (`cape.network`), Sysmon (`sysmon.evtx`) or
    capemon (`capemon.derived`) builds it; capemon names no source port.
    """
    event: Event = {
        "@timestamp": at(seconds).isoformat(),
        "event": {
            "id": f"{dataset}|{address}|{port}|{source_port}|{seconds}",
            "action": "network-connection",
            "dataset": dataset,
            "module": dataset.split(".", maxsplit=1)[0],
        },
        "destination": {"ip": address, "port": port},
        "tartarus": {"lan": {"simulated": True}},
    }
    if source_port is not None:
        event["source"] = {"ip": "192.168.150.10", "port": source_port}
    return event


def pcap_row(address: str, port: int, source_port: int, seconds: float = 1) -> Event:
    return connection("cape.network", address, port, source_port, seconds)


def sysmon_row(address: str, port: int, source_port: int, seconds: float = 1) -> Event:
    return connection("sysmon.evtx", address, port, source_port, seconds)


def capemon_row(address: str, port: int, seconds: float = 1) -> Event:
    return connection("capemon.derived", address, port, None, seconds)


def attempts(events: list[Event]) -> int:
    summary = lan_summary(events, LAN_HOSTS)
    assert summary is not None
    return summary.totals.attempts


def test_the_same_connection_from_the_pcap_sysmon_and_capemon_is_one_attempt() -> None:
    events = [
        pcap_row(FILE_SERVER, 445, 50001),
        sysmon_row(FILE_SERVER, 445, 50001),
        capemon_row(FILE_SERVER, 445),
    ]

    assert attempts(events) == 1


def test_a_connection_the_pcap_and_sysmon_both_saw_is_the_pcaps_whichever_comes_first() -> None:
    events = [sysmon_row(FILE_SERVER, 445, 50001, seconds=1), pcap_row(FILE_SERVER, 445, 50001, 2)]

    summary = lan_summary(events, LAN_HOSTS)

    assert summary is not None
    [use] = summary.hosts[0].services
    assert (use.attempts, use.first) == (1, at(2))


def test_connections_from_two_source_ports_are_two_attempts() -> None:
    events = [sysmon_row(FILE_SERVER, 3389, 50001), sysmon_row(FILE_SERVER, 3389, 50002)]

    assert attempts(events) == 2


def test_a_capemon_connect_is_dropped_when_another_source_has_the_same_endpoint() -> None:
    events = [sysmon_row(FILE_SERVER, 3389, 50001), capemon_row(FILE_SERVER, 3389)]

    assert attempts(events) == 1


def test_connects_only_capemon_saw_are_each_an_attempt() -> None:
    events = [capemon_row(FILE_SERVER, 3389, 1), capemon_row(FILE_SERVER, 3389, 2)]

    assert attempts(events) == 2


def test_a_capemon_connect_to_another_port_is_not_covered_by_a_flow() -> None:
    events = [sysmon_row(FILE_SERVER, 445, 50001), capemon_row(FILE_SERVER, 3389)]

    assert attempts(events) == 2


def test_a_connection_flagged_for_an_address_outside_the_preset_is_not_a_lan_attempt() -> None:
    assert attempts([sysmon_row("192.168.150.1", 445, 50001)]) == 0
