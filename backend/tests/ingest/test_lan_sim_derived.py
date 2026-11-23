"""The derived events of the `lan-sim` normaliser: sweep, fan-out and credential spray."""

from pathlib import Path
from typing import Any

import pytest

from app.ingest.capemon import CapemonNormalizer
from app.ingest.ecs import event_id
from app.ingest.lan_sim import LanSimNormalizer
from tests.ingest.contract import check_normalizer_contract
from tests.ingest.lan_sim_cases import (
    ANALYSIS_ID,
    LAN_HOSTS,
    at,
    context_of,
    login,
    write_log,
)
from tests.ingest.reports import call, process, report_of

Event = dict[str, Any]
ADDRESSES = list(LAN_HOSTS)
WORKSTATIONS = [a for a in ADDRESSES if LAN_HOSTS[a].role == "workstation"]


def stamp_of(seconds: float) -> str:
    return at(seconds).strftime("%Y-%m-%d %H:%M:%S,%f")[:-3]


def connect(address: str, port: int, seconds: float) -> dict[str, Any]:
    return call("connect", {"ip": address, "port": str(port)}, timestamp=stamp_of(seconds))


def sweeping(pid: int, addresses: list[str], port: int, step: float, start: float = 0) -> Any:
    calls = [connect(a, port, start + n * step) for n, a in enumerate(addresses)]
    return process(pid, calls, name=f"p{pid}.exe")


def tcp_flow(address: str, port: int, seconds: float) -> dict[str, Any]:
    return {"src": "192.168.150.10", "sport": 50000, "dst": address, "dport": port, "time": seconds}


def run(
    report: dict[str, Any], tmp_path: Path | None = None, log: list[Any] | None = None
) -> list[Event]:
    if tmp_path is not None and log is not None:
        write_log(tmp_path, log)
    context = context_of(tmp_path)
    return list(LanSimNormalizer().normalise(report, context))


def derived(events: list[Event], action: str | None = None) -> list[Event]:
    wanted = action and {action}
    return [
        e
        for e in events
        if e["event"]["dataset"] == "lan-sim.derived"
        and (wanted is None or e["event"]["action"] in wanted)
    ]


def capemon_connect_ids(report: dict[str, Any]) -> list[str]:
    return [
        e["event"]["id"]
        for e in CapemonNormalizer().normalise(report, context_of(None))
        if e["event"]["action"] == "network-connection"
    ]


# --- sweep -------------------------------------------------------------------------------------


def test_five_hosts_on_one_port_within_thirty_seconds_are_one_sweep(tmp_path: Path) -> None:
    report = report_of(sweeping(7, WORKSTATIONS[:5], 445, step=7.5))

    [sweep] = derived(run(report), "lan-sweep")

    assert sweep["tartarus"]["lan"]["count"] == 5


def test_four_hosts_are_no_sweep(tmp_path: Path) -> None:
    report = report_of(sweeping(7, WORKSTATIONS[:4], 445, step=1))

    assert derived(run(report)) == []


def test_a_sweep_of_thirty_one_seconds_is_no_sweep() -> None:
    report = report_of(sweeping(7, WORKSTATIONS[:5], 445, step=7.75))

    assert derived(run(report), "lan-sweep") == []


def test_a_sweep_event_says_who_swept_what_and_which_hosts() -> None:
    report = report_of(sweeping(7, WORKSTATIONS[:5], 445, step=2))

    [sweep] = derived(run(report), "lan-sweep")

    assert sweep["event"]["kind"] == "event"
    assert sweep["event"]["category"] == ["network"]
    assert sweep["event"]["type"] == ["connection"]
    assert sweep["event"]["dataset"] == "lan-sim.derived"
    assert sweep["event"]["module"] == "lan-sim"
    assert sweep["tartarus"]["lane"] == "network"
    assert sweep["@timestamp"] == "2026-11-23T12:00:00.000Z"
    assert sweep["process"]["pid"] == 7
    assert "thread" not in sweep["process"]
    assert sweep["destination"] == {"port": 445}
    assert sweep["tartarus"]["lan"] == {
        "simulated": True,
        "count": 5,
        "service": "smb",
        "preset": "small-office",
    }
    assert sweep["related"]["hosts"] == [LAN_HOSTS[a].fqdn for a in WORKSTATIONS[:5]]
    assert sweep["related"]["ip"] == WORKSTATIONS[:5]
    assert sweep["related"]["events"] == capemon_connect_ids(report)
    assert "p7.exe" in sweep["tartarus"]["summary"]
    assert "5 fake hosts" in sweep["tartarus"]["summary"]
    assert "port 445" in sweep["tartarus"]["summary"]


def test_a_long_scan_is_one_event_per_window_not_one_per_host() -> None:
    report = report_of(sweeping(7, WORKSTATIONS * 3, 445, step=1))

    assert len(derived(run(report), "lan-sweep")) == 1


def test_a_sweep_of_a_port_no_host_serves_has_no_service() -> None:
    report = report_of(sweeping(7, WORKSTATIONS[:5], 8080, step=1))

    [sweep] = derived(run(report), "lan-sweep")

    assert "service" not in sweep["tartarus"]["lan"]


def test_one_process_on_two_ports_gives_one_event_per_port() -> None:
    both = process(
        7,
        [connect(a, port, n) for port in (445, 3389) for n, a in enumerate(WORKSTATIONS[:5])],
        name="p7.exe",
    )

    sweeps = derived(run(report_of(both)), "lan-sweep")

    assert sorted(s["destination"]["port"] for s in sweeps) == [445, 3389]


def test_the_contacts_of_two_processes_are_not_added_together() -> None:
    report = report_of(
        sweeping(7, WORKSTATIONS[:3], 445, step=1), sweeping(8, WORKSTATIONS[3:6], 445, step=1)
    )

    assert derived(run(report), "lan-sweep") == []


def test_two_processes_that_each_sweep_give_two_events() -> None:
    report = report_of(
        sweeping(7, WORKSTATIONS[:5], 445, step=1), sweeping(8, WORKSTATIONS[:5], 445, step=1)
    )

    sweeps = derived(run(report), "lan-sweep")

    assert sorted(s["process"]["pid"] for s in sweeps) == [7, 8]


def test_connects_to_addresses_that_are_not_fake_hosts_do_not_count() -> None:
    elsewhere = [f"10.0.0.{n}" for n in range(10)]
    report = report_of(sweeping(7, elsewhere, 445, step=1))

    assert derived(run(report)) == []


def test_a_sweep_the_pcap_alone_saw_has_flows_but_no_process() -> None:
    report = report_of()
    report["network"] = {"tcp": [tcp_flow(a, 445, n) for n, a in enumerate(WORKSTATIONS[:5])]}

    [sweep] = derived(run(report), "lan-sweep")

    assert "process" not in sweep
    assert "events" not in sweep["related"]
    assert sweep["@timestamp"] == "2026-11-23T12:00:00.000Z"


def test_a_flow_capemon_also_saw_is_one_contact_not_two() -> None:
    report = report_of(sweeping(7, WORKSTATIONS[:3], 445, step=1))
    report["network"] = {"tcp": [tcp_flow(a, 445, n + 2) for n, a in enumerate(WORKSTATIONS[:5])]}

    sweeps = derived(run(report), "lan-sweep")

    assert sweeps == []


def test_a_closed_port_scan_only_the_report_knows_is_still_a_sweep() -> None:
    report = report_of(sweeping(7, WORKSTATIONS[:6], 23, step=0.5))

    [sweep] = derived(run(report), "lan-sweep")

    assert sweep["destination"]["port"] == 23


# --- fan-out -----------------------------------------------------------------------------------


def fan_out_report(
    seconds_for_last: float = 3, services: tuple[int, ...] = (445, 445, 3389, 3389)
) -> Any:
    hosts = WORKSTATIONS[: len(services)]
    calls = [connect(a, p, n) for n, (a, p) in enumerate(zip(hosts, services, strict=True))]
    calls[-1] = connect(hosts[-1], services[-1], seconds_for_last)
    return report_of(process(7, calls, name="p7.exe"))


def test_four_hosts_over_two_services_are_one_fan_out() -> None:
    [fan_out] = derived(run(fan_out_report()), "lan-fan-out")

    assert fan_out["tartarus"]["lan"]["count"] == 4
    assert fan_out["tartarus"]["lan"]["service"] == ["smb", "rdp"]
    assert fan_out["event"]["type"] == ["connection"]
    assert fan_out["process"]["pid"] == 7
    assert "destination" not in fan_out
    assert "smb, rdp" in fan_out["tartarus"]["summary"]


def test_four_hosts_over_one_service_are_no_fan_out() -> None:
    assert derived(run(fan_out_report(services=(445, 445, 445, 445))), "lan-fan-out") == []


def test_three_hosts_over_two_services_are_no_fan_out() -> None:
    assert derived(run(fan_out_report(services=(445, 445, 3389))), "lan-fan-out") == []


def test_a_fan_out_takes_five_minutes_exactly_and_not_two_seconds_more() -> None:
    assert len(derived(run(fan_out_report(300)), "lan-fan-out")) == 1
    assert derived(run(fan_out_report(302)), "lan-fan-out") == []


# --- credential spray --------------------------------------------------------------------------


def attempts(users: list[str], hosts: list[str], step: float = 10) -> list[dict[str, Any]]:
    return [
        login(user=user, host=host, seconds=1 + n * step)
        for n, (user, host) in enumerate(zip(users, hosts, strict=True))
    ]


FQDNS = [LAN_HOSTS[a].fqdn for a in WORKSTATIONS]


def test_the_same_user_name_on_three_hosts_in_five_minutes_is_one_spray(tmp_path: Path) -> None:
    events = run({}, tmp_path, attempts(["admin"] * 3, FQDNS[:3]))

    [spray] = derived(events, "lan-credential-spray")

    assert spray["event"]["category"] == ["network", "authentication"]
    assert spray["event"]["type"] == ["info"]
    assert spray["user"] == {"name": "admin"}
    assert spray["tartarus"]["lan"] == {
        "simulated": True,
        "count": 3,
        "service": "smb",
        "preset": "small-office",
    }
    assert spray["related"]["hosts"] == FQDNS[:3]
    login_ids = [e["event"]["id"] for e in events if e["event"]["action"] == "lan-login-attempt"]
    assert spray["related"]["events"] == login_ids
    assert "admin" in spray["tartarus"]["summary"]
    assert "3 fake hosts" in spray["tartarus"]["summary"]
    assert "network" not in spray


def test_two_hosts_are_no_spray(tmp_path: Path) -> None:
    assert (
        derived(run({}, tmp_path, attempts(["admin"] * 2, FQDNS[:2])), "lan-credential-spray") == []
    )


def test_one_host_many_times_is_no_spray(tmp_path: Path) -> None:
    log = attempts(["admin"] * 30, FQDNS[:1] * 30, step=1)

    assert derived(run({}, tmp_path, log), "lan-credential-spray") == []


def test_different_user_names_are_not_one_spray(tmp_path: Path) -> None:
    log = attempts(["a", "b", "c"], FQDNS[:3])

    assert derived(run({}, tmp_path, log), "lan-credential-spray") == []


def test_the_user_name_is_compared_without_regard_to_case(tmp_path: Path) -> None:
    log = attempts(["Admin", "admin", "ADMIN"], FQDNS[:3])

    [spray] = derived(run({}, tmp_path, log), "lan-credential-spray")

    assert spray["user"] == {"name": "Admin"}


@pytest.mark.parametrize(("step", "count"), [(150, 1), (151, 0)])
def test_a_spray_takes_five_minutes_exactly_and_not_a_second_more(
    tmp_path: Path, step: float, count: int
) -> None:
    log = attempts(["admin"] * 3, FQDNS[:3], step=step)

    assert len(derived(run({}, tmp_path, log), "lan-credential-spray")) == count


def test_an_anonymous_attempt_is_not_part_of_a_spray(tmp_path: Path) -> None:
    log = attempts([""] * 3, FQDNS[:3])

    assert derived(run({}, tmp_path, log), "lan-credential-spray") == []


def test_a_spray_by_an_identified_process_names_it(tmp_path: Path) -> None:
    calls = [connect(a, 445, n) for n, a in enumerate(WORKSTATIONS[:3])]
    report = report_of(process(7, calls, name="p7.exe"))

    [spray] = derived(
        run(report, tmp_path, attempts(["admin"] * 3, FQDNS[:3])), "lan-credential-spray"
    )

    assert spray["process"]["pid"] == 7


# --- all of them -------------------------------------------------------------------------------


def test_without_the_log_file_the_report_still_gives_its_sweeps(tmp_path: Path) -> None:
    report = report_of(sweeping(7, WORKSTATIONS[:5], 445, step=1))

    events = list(LanSimNormalizer().normalise(report, context_of(tmp_path)))

    assert [e["event"]["action"] for e in events] == ["lan-sweep"]


def test_derived_events_follow_the_log_ones_oldest_first_with_ids_from_their_order(
    tmp_path: Path,
) -> None:
    report = report_of(
        sweeping(7, WORKSTATIONS[:5], 445, step=1, start=100),
        sweeping(8, WORKSTATIONS[:5], 3389, step=1, start=10),
    )

    events = run(report, tmp_path, [login()])

    assert [e["event"]["action"] for e in events] == ["lan-login-attempt", "lan-sweep", "lan-sweep"]
    assert [e["process"]["pid"] for e in events[1:]] == [8, 7]
    assert [e["event"]["id"] for e in events[1:]] == [
        event_id(ANALYSIS_ID, "lan-sim", "derived", 0),
        event_id(ANALYSIS_ID, "lan-sim", "derived", 1),
    ]
    assert [e["event"]["sequence"] for e in events] == [0, 1, 2]


def test_the_contract_holds_with_derived_events(tmp_path: Path) -> None:
    write_log(tmp_path, attempts(["admin"] * 3, FQDNS[:3]))
    report = report_of(sweeping(7, WORKSTATIONS[:5], 445, step=1))

    events = check_normalizer_contract(LanSimNormalizer(), report, context_of(tmp_path))

    assert {"lan-sweep", "lan-credential-spray"} <= {e["event"]["action"] for e in events}
