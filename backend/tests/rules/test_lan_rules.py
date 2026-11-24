"""The fake-LAN rules in `rules/sigma/tartarus/`, run through the real normalisers and engine.

Every case builds the events the way an analysis does (the report, the daemon's log) so a rule is
tested on the shape it will see, and each rule has a case where it must stay quiet.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
import yaml

from app.db.models.analysis import Severity
from app.ingest.cape_network import CapeNetworkNormalizer
from app.ingest.capemon import CapemonNormalizer
from app.ingest.lan_sim import LanSimNormalizer
from app.ingest.protocol import IngestContext, LanHost
from app.rules.attack import attack_fields
from app.rules.engine import Emit, SigmaEngine
from app.rules.loader import load_rule_file, load_rules
from app.rules.rule import Rule, Validity
from app.views.attack import AlertTechniques, build_matrix
from app.views.attack_table import load_attack_table
from tests.ingest.lan_sim_cases import (
    FILE_SERVER,
    GUEST,
    LAN_HOSTS,
    at,
    context_of,
    file_write,
    login,
    service_request,
    share_access,
    write_log,
)
from tests.ingest.reports import call, process, report_of
from tests.rules.support import TARTARUS_RULESET, rule_yaml, simple_detection

Event = dict[str, Any]
WORKSTATIONS = [a for a, host in LAN_HOSTS.items() if host.role == "workstation"]


@dataclass(frozen=True)
class Expected:
    id: str
    category: str
    level: str
    techniques: tuple[str, ...]
    tactics: tuple[str, ...]


LAN_RULES = {
    "lan_connect_smb": Expected(
        "ee02f7ee-579c-4de0-bda9-fdcb238a0c23",
        "network_connection",
        "informational",
        ("T1021.002",),
        ("Lateral Movement",),
    ),
    "lan_connect_rdp": Expected(
        "8c668a2f-914f-4182-9fd0-39308059076e",
        "network_connection",
        "low",
        ("T1021.001",),
        ("Lateral Movement",),
    ),
    "lan_connect_winrm": Expected(
        "2cf024f1-e282-49a1-99b0-b0ec6c3e8666",
        "network_connection",
        "low",
        ("T1021.006",),
        ("Lateral Movement",),
    ),
    "lan_connect_ssh": Expected(
        "5c9289b6-7343-4c39-aba8-165456dbba4e",
        "network_connection",
        "low",
        ("T1021.004",),
        ("Lateral Movement",),
    ),
    "lan_connect_mssql": Expected(
        "7a2d5e44-c221-4c17-96a0-601539dc24d7",
        "network_connection",
        "low",
        ("T1210",),
        ("Lateral Movement",),
    ),
    "lan_admin_share_access": Expected(
        "c3c54cee-48ae-46d0-8e5b-7577b96d4dc4",
        "lan_share_access",
        "medium",
        ("T1021.002",),
        ("Lateral Movement",),
    ),
    "lan_executable_written_to_admin_share": Expected(
        "e3ef143d-8244-498f-8749-c9f5a6cc5cf4",
        "lan_file_write",
        "high",
        ("T1570", "T1021.002"),
        ("Lateral Movement",),
    ),
    "lan_service_created_over_smb": Expected(
        "b67fe089-b2ca-4d5b-81e2-4112a6d3da97",
        "lan_service_request",
        "high",
        ("T1569.002", "T1021.002"),
        ("Execution", "Lateral Movement"),
    ),
    "lan_credential_spray": Expected(
        "8380aee6-4387-4b5c-b91a-d0bed3b7ec7f",
        "lan_credential_spray",
        "high",
        ("T1110.003",),
        ("Credential Access",),
    ),
    "lan_sweep": Expected(
        "cac194e8-c276-42a6-a9a0-24e7738b0b2e",
        "lan_sweep",
        "medium",
        ("T1046",),
        ("Discovery",),
    ),
    "lan_fan_out": Expected(
        "ac57ee12-015f-42e6-a2a8-aea144679062",
        "lan_fan_out",
        "medium",
        ("T1021", "T1210"),
        ("Lateral Movement",),
    ),
}
CONNECTION_PORTS = {
    "lan_connect_smb": [445],
    "lan_connect_rdp": [3389],
    "lan_connect_winrm": [5985, 5986],
    "lan_connect_ssh": [22],
    "lan_connect_mssql": [1433],
}
DERIVED = {"lan_sweep", "lan_fan_out", "lan_credential_spray"}


@pytest.fixture(scope="module")
def rules() -> dict[str, Rule]:
    return {rule.path.stem: rule for rule in load_rules(TARTARUS_RULESET)}


def stamp_of(seconds: float) -> str:
    return at(seconds).strftime("%Y-%m-%d %H:%M:%S,%f")[:-3]


def connect(address: str, port: int, seconds: float = 1) -> dict[str, Any]:
    return call("connect", {"ip": address, "port": str(port)}, timestamp=stamp_of(seconds))


def tcp_flow(address: str, port: int, seconds: float = 1) -> dict[str, Any]:
    return {"src": GUEST, "sport": 50000, "dst": address, "dport": port, "time": seconds}


def report_connecting(
    contacts: list[tuple[str, int]], *, name: str = "sample.exe", step: float = 1
) -> dict[str, Any]:
    """One process that connects to each `(address, port)` in turn, `step` seconds apart; the pcap
    has a flow for each."""
    calls = [connect(address, port, n * step) for n, (address, port) in enumerate(contacts)]
    report = report_of(process(7, calls, name=name))
    report["network"] = {
        "tcp": [tcp_flow(address, port, n * step) for n, (address, port) in enumerate(contacts)]
    }
    return report


def events_of(
    tmp_path: Path,
    report: dict[str, Any] | None = None,
    log: list[dict[str, Any]] | None = None,
    lan_hosts: dict[str, LanHost] | None = None,
) -> list[Event]:
    """What an analysis indexes for `report` and the daemon's `log`, oldest first."""
    if log is not None:
        write_log(tmp_path, log)
    context = context_of(tmp_path, lan_hosts)
    report = report or report_of()
    events = [
        *CapemonNormalizer().normalise(report, context),
        *CapeNetworkNormalizer().normalise(report, context),
        *LanSimNormalizer().normalise(report, context),
    ]
    return sorted(events, key=lambda event: event["@timestamp"])


def detections(rules: dict[str, Rule], events: list[Event]) -> list[Event]:
    engine = SigmaEngine(rules.values(), IngestContext(6, at(0)))
    return [
        outcome.detection
        for event in events
        for outcome in engine.process(event)
        if isinstance(outcome, Emit)
    ]


def fired(rules: dict[str, Rule], events: list[Event]) -> set[str]:
    stem_of = {rule.id: stem for stem, rule in rules.items()}
    return {stem_of[d["rule"]["id"]] for d in detections(rules, events)}


# --- the files -----------------------------------------------------------------------------------


def test_the_lan_rules_are_the_files_named_lan_in_the_tartarus_folder(
    rules: dict[str, Rule],
) -> None:
    assert {stem for stem in rules if stem.startswith("lan_")} == set(LAN_RULES)


@pytest.mark.parametrize("stem", LAN_RULES)
def test_a_lan_rule_is_valid_with_its_category_level_and_techniques(
    rules: dict[str, Rule], stem: str
) -> None:
    rule, expected = rules[stem], LAN_RULES[stem]

    assert (rule.validity, rule.error) == (Validity.VALID, None)
    assert (rule.id, rule.logsource_category, rule.level) == (
        expected.id,
        expected.category,
        expected.level,
    )
    attack = attack_fields(rule.tags)
    assert tuple(attack.techniques) == expected.techniques
    assert set(attack.tactics) == set(expected.tactics)


@pytest.mark.parametrize("stem", LAN_RULES)
def test_a_lan_rule_is_written_in_the_house_format(stem: str) -> None:
    document = yaml.safe_load((TARTARUS_RULESET / f"{stem}.yml").read_text())

    assert document["author"] == "Tartarus"
    assert document["status"] == "experimental"
    assert document["logsource"]["product"] == "windows"
    assert document["falsepositives"]
    assert document["date"]


def test_every_technique_a_tartarus_rule_names_is_in_the_attack_table(
    rules: dict[str, Rule],
) -> None:
    table = load_attack_table()

    unknown = {
        stem: technique
        for stem, rule in rules.items()
        for technique in attack_fields(rule.tags).techniques
        if table.technique(technique) is None
    }

    assert unknown == {}, "the ATT&CK table (scripts/build-attack-table.py) has no such technique"


# --- connections to a fake host (network_connection) ---------------------------------------------


def connection_cases() -> list[tuple[str, int]]:
    return [(stem, port) for stem, ports in CONNECTION_PORTS.items() for port in ports]


@pytest.mark.parametrize(("stem", "port"), connection_cases())
def test_a_process_connecting_to_a_fake_host_on_the_services_port_raises_that_rule_only(
    rules: dict[str, Rule], tmp_path: Path, stem: str, port: int
) -> None:
    events = events_of(tmp_path, report_connecting([(FILE_SERVER, port)]))

    [alert] = detections(rules, events)

    assert alert["rule"]["id"] == LAN_RULES[stem].id
    assert alert["process"]["name"] == "sample.exe"


@pytest.mark.parametrize("stem", CONNECTION_PORTS)
def test_the_connection_rule_ignores_a_port_that_is_not_its_service(
    rules: dict[str, Rule], tmp_path: Path, stem: str
) -> None:
    other_ports = [p for other, ports in CONNECTION_PORTS.items() if other != stem for p in ports]

    events = events_of(tmp_path, report_connecting([(FILE_SERVER, 8080)]))
    assert stem not in fired(rules, events)
    for port in other_ports:
        wrong = events_of(tmp_path, report_connecting([(FILE_SERVER, port)]))
        assert stem not in fired(rules, wrong)


@pytest.mark.parametrize(("stem", "port"), connection_cases())
def test_a_system_process_connecting_does_not_raise_the_connection_rule(
    rules: dict[str, Rule], tmp_path: Path, stem: str, port: int
) -> None:
    events = events_of(tmp_path, report_connecting([(FILE_SERVER, port)], name="svchost.exe"))

    assert fired(rules, events) == set()


@pytest.mark.parametrize(("stem", "port"), connection_cases())
def test_a_connection_to_an_address_that_is_not_a_fake_host_raises_nothing(
    rules: dict[str, Rule], tmp_path: Path, stem: str, port: int
) -> None:
    events = events_of(tmp_path, report_connecting([("192.168.150.99", port)]))

    assert fired(rules, events) == set()


@pytest.mark.parametrize(("stem", "port"), connection_cases())
def test_a_flow_no_process_is_known_for_raises_nothing(
    rules: dict[str, Rule], tmp_path: Path, stem: str, port: int
) -> None:
    report = report_connecting([(FILE_SERVER, port)])
    report["behavior"] = {"processes": []}

    assert fired(rules, events_of(tmp_path, report)) == set()


def test_a_connection_without_the_feature_raises_nothing(
    rules: dict[str, Rule], tmp_path: Path
) -> None:
    events = events_of(tmp_path, report_connecting([(FILE_SERVER, 445)]), lan_hosts={})

    assert fired(rules, events) == set()


# --- the share, the file and the service (the daemon's log) -------------------------------------


@pytest.mark.parametrize("share", ["ADMIN$", "C$", "IPC$", "admin$"])
def test_a_tree_connect_to_an_administrative_share_raises_the_admin_share_rule(
    rules: dict[str, Rule], tmp_path: Path, share: str
) -> None:
    events = events_of(tmp_path, log=[share_access(share=share, path="", operation="tree-connect")])

    assert fired(rules, events) == {"lan_admin_share_access"}


@pytest.mark.parametrize("share", ["Public", "Finance", "ADMIN", "ADMIN$$"])
def test_a_share_that_is_not_administrative_raises_nothing(
    rules: dict[str, Rule], tmp_path: Path, share: str
) -> None:
    events = events_of(tmp_path, log=[share_access(share=share)])

    assert fired(rules, events) == set()


@pytest.mark.parametrize(
    "path", ["\\evil.exe", "\\Windows\\Temp\\payload.dll", "\\run.bat", "\\x.ps1", "\\EVIL.EXE"]
)
@pytest.mark.parametrize("share", ["ADMIN$", "C$"])
def test_an_executable_written_to_an_administrative_share_raises_the_transfer_rule(
    rules: dict[str, Rule], tmp_path: Path, share: str, path: str
) -> None:
    events = events_of(tmp_path, log=[file_write(share=share, path=path)])

    assert fired(rules, events) == {"lan_executable_written_to_admin_share"}


@pytest.mark.parametrize(
    ("share", "path"),
    [
        ("ADMIN$", "\\notes.txt"),
        ("ADMIN$", "\\evil.exe.txt"),
        ("ADMIN$", "\\dir.exe\\readme"),
        ("Public", "\\evil.exe"),
        ("IPC$", "\\evil.exe"),
    ],
)
def test_a_write_that_is_not_an_executable_on_an_administrative_share_raises_nothing(
    rules: dict[str, Rule], tmp_path: Path, share: str, path: str
) -> None:
    events = events_of(tmp_path, log=[file_write(share=share, path=path)])

    assert fired(rules, events) == set()


def test_a_service_created_over_smb_raises_the_service_rule(
    rules: dict[str, Rule], tmp_path: Path
) -> None:
    events = events_of(tmp_path, log=[service_request()])

    assert fired(rules, events) == {"lan_service_created_over_smb"}


@pytest.mark.parametrize("name", ["svcctl StartService", "svcctl DeleteService", "srvsvc bind"])
def test_another_service_request_raises_nothing(
    rules: dict[str, Rule], tmp_path: Path, name: str
) -> None:
    events = events_of(tmp_path, log=[service_request(name=name)])

    assert fired(rules, events) == set()


# --- derived events -----------------------------------------------------------------------------


def spray(users: list[str], hosts: list[str], step: float = 10) -> list[dict[str, Any]]:
    return [
        login(host=LAN_HOSTS[address].fqdn, user=user, seconds=1 + n * step)
        for n, (address, user) in enumerate(zip(hosts, users, strict=True))
    ]


def test_one_user_name_tried_on_three_hosts_raises_the_spray_rule(
    rules: dict[str, Rule], tmp_path: Path
) -> None:
    attempts = spray(["admin"] * 3, WORKSTATIONS[:3])

    assert fired(rules, events_of(tmp_path, log=attempts)) == {"lan_credential_spray"}


def test_a_user_name_tried_on_two_hosts_raises_no_spray(
    rules: dict[str, Rule], tmp_path: Path
) -> None:
    attempts = spray(["admin"] * 2, WORKSTATIONS[:2])

    assert fired(rules, events_of(tmp_path, log=attempts)) == set()


def test_three_hosts_with_three_user_names_are_no_spray(
    rules: dict[str, Rule], tmp_path: Path
) -> None:
    attempts = spray(["a", "b", "c"], WORKSTATIONS[:3])

    assert fired(rules, events_of(tmp_path, log=attempts)) == set()


def contacts(ports: list[int], hosts: list[str]) -> list[tuple[str, int]]:
    return list(zip(hosts, ports, strict=True))


def test_five_hosts_on_one_port_raise_the_sweep_rule_and_not_the_fan_out(
    rules: dict[str, Rule], tmp_path: Path
) -> None:
    report = report_connecting(contacts([445] * 5, WORKSTATIONS[:5]), step=5)

    assert fired(rules, events_of(tmp_path, report)) & DERIVED == {"lan_sweep"}


def test_four_hosts_on_one_port_raise_no_sweep(rules: dict[str, Rule], tmp_path: Path) -> None:
    report = report_connecting(contacts([445] * 4, WORKSTATIONS[:4]), step=5)

    assert fired(rules, events_of(tmp_path, report)) & DERIVED == set()


def test_a_slow_scan_of_five_hosts_raises_no_sweep(rules: dict[str, Rule], tmp_path: Path) -> None:
    report = report_connecting(contacts([445] * 5, WORKSTATIONS[:5]), step=20)

    assert "lan_sweep" not in fired(rules, events_of(tmp_path, report))


def test_four_hosts_over_two_services_raise_the_fan_out_rule_and_not_the_sweep(
    rules: dict[str, Rule], tmp_path: Path
) -> None:
    report = report_connecting(contacts([445, 3389, 445, 3389], WORKSTATIONS[:4]), step=20)

    assert fired(rules, events_of(tmp_path, report)) & DERIVED == {"lan_fan_out"}


def test_four_hosts_over_one_service_raise_no_fan_out(
    rules: dict[str, Rule], tmp_path: Path
) -> None:
    report = report_connecting(contacts([445] * 4, WORKSTATIONS[:4]), step=20)

    assert "lan_fan_out" not in fired(rules, events_of(tmp_path, report))


# --- every category carries a rule end to end ---------------------------------------------------

CATEGORY_RULES = {
    "lan_authentication": ("User: Administrator", lambda: [login()]),
    "lan_share_access": ("Share: ADMIN$", lambda: [share_access()]),
    "lan_file_write": ("Share: ADMIN$", lambda: [file_write()]),
    "lan_service_request": ("RequestName: svcctl CreateService", lambda: [service_request()]),
}


@pytest.mark.parametrize("category", CATEGORY_RULES)
def test_a_custom_rule_of_a_log_category_matches_its_event_and_not_another_one(
    tmp_path: Path, category: str
) -> None:
    selection, make_log = CATEGORY_RULES[category]
    path = tmp_path / "custom.yml"
    path.write_text(rule_yaml(simple_detection(selection), category=category))
    rule = load_rule_file(path)
    assert rule.validity is Validity.VALID, rule.error
    other_log = [r for c, (_, make) in CATEGORY_RULES.items() if c != category for r in make()]
    (own_dir, else_dir) = (tmp_path / "own", tmp_path / "else")
    own_dir.mkdir()
    else_dir.mkdir()

    own = events_of(own_dir, log=make_log())
    elsewhere = events_of(else_dir, log=other_log)

    assert len(detections({"custom": rule}, own)) == 1
    assert detections({"custom": rule}, elsewhere) == []


# --- the ATT&CK matrix --------------------------------------------------------------------------


def test_the_matrix_lists_an_admin_share_alert_under_lateral_movement(
    rules: dict[str, Rule], tmp_path: Path
) -> None:
    events = events_of(tmp_path, log=[share_access(share="ADMIN$")])
    [alert] = detections(rules, events)
    techniques = tuple(alert["threat"]["technique"]["id"])

    matrix = build_matrix(
        [AlertTechniques(alert["event"]["id"], Severity.MEDIUM, techniques)], load_attack_table()
    )

    [tactic] = matrix.tactics
    assert (tactic.id, [hit.id for hit in tactic.techniques]) == ("lateral-movement", ["T1021.002"])
    assert tactic.techniques[0].name == "SMB/Windows Admin Shares"


@pytest.mark.parametrize("stem", LAN_RULES)
def test_each_tactic_a_lan_rule_tags_has_one_of_its_techniques_in_the_matrix(
    rules: dict[str, Rule], stem: str
) -> None:
    rule = rules[stem]
    attack = attack_fields(rule.tags)
    matrix = build_matrix(
        [AlertTechniques("d1", Severity.MEDIUM, tuple(attack.techniques))],
        load_attack_table(),
    )

    names_in_matrix = {tactic.name for tactic in matrix.tactics}

    assert set(attack.tactics) <= names_in_matrix
