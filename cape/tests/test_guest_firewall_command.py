"""Tests of `bin/guest-firewall`, the command the entrypoint and libvirt's qemu hook run."""

import json
from dataclasses import asdict

import pytest
from fixtures.guest_samples import make_guest
from test_control_http import load_script
from test_guest_firewall import ROUTES, STARTED_XML
from test_lan_firewall import DC, GUEST_A, SESSION_A, FakeContainer, LanSession, LanTarget
from test_port_isolation import Bridge

from guest_engine.firewall import PortLedger
from guest_engine.lan_firewall import LanLedger
from guest_engine.media import MediaProblem
from guest_engine.media.errors import Fault
from guest_engine.registry import Registry

guest_firewall = load_script("guest-firewall")

# A second session on the same guest: analyses never share one, but the listing must not care.
SESSION_B_ON_LAB1 = LanSession("task-2", GUEST_A, (LanTarget("192.168.150.202", (9100,)),))
ENVIRONMENT = {"GUEST_SUBNET": "192.168.150.0/24", "GUEST_GATEWAY_IP": "192.168.150.1"}


class Programs:
    """The container's programs: `bridge`, and `nft`, `iptables` and `ip`, in the order called."""

    def __init__(self, nft, bridge):
        self.nft = nft
        self.bridge = bridge
        self.calls: list[str] = []

    def __call__(self, args, timeout=None):
        self.calls.append(args[0])
        program = self.bridge if args[0] == "bridge" else self.nft
        return program(args, timeout)


@pytest.fixture
def container(tmp_path):
    registry = Registry(tmp_path / "guests")
    registry.create(make_guest("lab1", "192.168.150.11"))
    nft = FakeContainer()
    programs = Programs(nft, Bridge())
    paths = guest_firewall.Paths(
        state=tmp_path / "state",
        registry=tmp_path / "guests",
        rules=tmp_path / "state" / "rules.nft",
    )

    def run(*arguments, environ=ENVIRONMENT, stdin=""):
        this = guest_firewall.Container(paths, programs, lambda: ROUTES, environ)
        return guest_firewall.main(list(arguments), stdin, this)

    return run, nft, paths, programs


def test_init_stores_the_policy_it_found_and_applies_a_ruleset_with_no_bound_port(container):
    run, nft, paths, _ = container

    assert run("init") == 0

    stored = json.loads((paths.state / "policy.json").read_text())
    assert stored["gateway"] == "192.168.150.1"
    assert "172.19.0.0/16" in stored["networks"]
    assert "vnet" not in nft.rulesets[-1]


def test_the_hook_binds_a_started_guest_using_the_policy_init_stored(container):
    run, nft, _paths, _ = container
    run("init")

    assert run("hook", "lab1", "started", "begin", "-", environ={}, stdin=STARTED_XML) == 0

    assert '"vnet10" . 00:14:22:8d:44:27 . 192.168.150.11' in nft.rulesets[-1]


def test_the_hook_unbinds_a_stopped_guest(container):
    run, nft, paths, _ = container
    run("init")
    run("hook", "lab1", "started", "begin", "-", environ={}, stdin=STARTED_XML)

    assert run("hook", "lab1", "stopped", "end", "-", environ={}) == 0

    assert "vnet10" not in nft.rulesets[-1]
    assert PortLedger(paths.state / "ports").ports() == []


def test_the_hook_before_init_fails_loudly_rather_than_applying_a_guess(container):
    run, nft, _, _ = container

    assert run("hook", "lab1", "started", "begin", "-", environ={}, stdin=STARTED_XML) == 1
    assert nft.rulesets == []


def test_a_ruleset_nft_refuses_is_a_failure_the_caller_sees(container):
    run, nft, _, _ = container
    nft.returncode = 1

    assert run("init") == 1


def test_an_unknown_command_is_a_usage_error(container):
    run, _, _, _ = container

    assert run("explode") == 2
    assert run() == 2


# --- the hook isolates the port before the firewall binds it ------------------------------------


def test_the_hook_isolates_the_port_of_a_started_guest_before_binding_it(container):
    run, _nft, _paths, programs = container
    run("init")
    programs.calls.clear()

    assert run("hook", "lab1", "started", "begin", "-", environ={}, stdin=STARTED_XML) == 0

    assert programs.bridge.isolated == {"vnet10"}
    assert programs.calls.index("bridge") < programs.calls.index("nft")


def test_a_port_that_cannot_be_isolated_is_not_recorded_so_the_guest_has_no_connectivity(
    container, capsys
):
    run, nft, paths, programs = container
    run("init")
    programs.bridge.set_fails = {"vnet10"}
    rulesets_before = len(nft.rulesets)

    assert run("hook", "lab1", "started", "begin", "-", environ={}, stdin=STARTED_XML) == 1

    assert PortLedger(paths.state / "ports").ports() == []
    assert len(nft.rulesets) == rulesets_before
    assert "vnet10" in capsys.readouterr().err


def test_a_port_whose_flag_reads_back_off_is_not_recorded_either(container):
    run, _nft, paths, programs = container
    run("init")
    programs.bridge.ignores_set = {"vnet10"}

    assert run("hook", "lab1", "started", "begin", "-", environ={}, stdin=STARTED_XML) == 1

    assert PortLedger(paths.state / "ports").ports() == []


def test_a_stopped_guest_runs_no_bridge_command(container):
    run, _nft, _paths, programs = container
    run("init")
    run("hook", "lab1", "started", "begin", "-", environ={}, stdin=STARTED_XML)
    programs.bridge.commands.clear()

    run("hook", "lab1", "stopped", "end", "-", environ={})

    assert programs.bridge.commands == []


def test_a_domain_with_no_port_on_the_guest_bridge_runs_no_bridge_command(container):
    run, _nft, _paths, programs = container
    run("init")
    xml = STARTED_XML.replace("tt-guest", "elsewhere")

    assert run("hook", "lab1", "started", "begin", "-", environ={}, stdin=xml) == 0

    assert programs.bridge.commands == []


# --- the fake local network's sessions ------------------------------------------------------------


def test_the_hook_rebuilds_an_open_session_because_the_ledger_is_in_the_state_directory(container):
    run, nft, paths, _ = container
    run("init")
    LanLedger(paths.state / "lan").record(SESSION_A)

    assert run("hook", "lab1", "started", "begin", "-", environ={}, stdin=STARTED_XML) == 0

    assert f"{GUEST_A} . {DC} . 445" in nft.rulesets[-1]
    assert nft.chains["OUTPUT"] != []
    assert DC in nft.routes


def test_init_closes_every_session_a_dead_container_left_and_removes_what_it_added(container):
    run, nft, paths, _ = container
    run("init")
    LanLedger(paths.state / "lan").record(SESSION_A)
    run("hook", "lab1", "started", "begin", "-", environ={}, stdin=STARTED_XML)

    assert run("init") == 0

    assert LanLedger(paths.state / "lan").sessions() == []
    assert nft.state() == ([], {"INPUT": [], "OUTPUT": []}, {})
    assert "lan_tcp" not in nft.rulesets[-1]


def test_a_failing_iptables_is_a_failure_the_caller_sees(container):
    run, nft, _, _ = container
    run("init")
    nft.chains["OUTPUT"] = ["-j ACCEPT -m comment --comment tartarus-lan"]
    nft.iptables_returncode = 1

    assert run("init") == 1


# --- the control service drives the sessions through lan-open, lan-close and lan-list ---------


def session_json(session=SESSION_A) -> str:
    return json.dumps(asdict(session))


def test_lan_open_applies_the_session_it_reads_from_stdin_and_prints_nothing(container, capsys):
    run, nft, paths, _ = container
    run("init")

    assert run("lan-open", stdin=session_json()) == 0

    assert f"{GUEST_A} . {DC} . 445" in nft.rulesets[-1]
    assert LanLedger(paths.state / "lan").sessions() == [SESSION_A]
    assert capsys.readouterr() == ("", "")


def test_lan_open_uses_the_policy_init_stored_not_the_environment(container):
    run, _nft, _paths, _ = container
    run("init")

    assert run("lan-open", environ={}, stdin=session_json()) == 0


def test_lan_open_before_init_fails_loudly_and_records_nothing(container, capsys):
    run, nft, paths, _ = container

    assert run("lan-open", stdin=session_json()) == 1

    assert nft.rulesets == []
    assert LanLedger(paths.state / "lan").sessions() == []
    assert "guest-firewall:" in capsys.readouterr().err


@pytest.mark.parametrize(
    "stdin",
    [
        "",
        "not json",
        "[]",
        '{"key": "task-1"}',
        json.dumps({**asdict(SESSION_A), "guest_address": "not-an-address"}),
        json.dumps(
            {**asdict(SESSION_A), "targets": [{"address": "172.19.0.2", "tcp_ports": [80]}]}
        ),
        json.dumps({**asdict(SESSION_A), "targets": [{"address": DC, "tcp_ports": ["445"]}]}),
        json.dumps({**asdict(SESSION_A), "key": "../escape"}),
    ],
)
def test_lan_open_refuses_a_session_that_is_not_valid_and_changes_nothing(container, capsys, stdin):
    run, nft, paths, _ = container
    run("init")
    rulesets_before = len(nft.rulesets)

    assert run("lan-open", stdin=stdin) == 1

    assert len(nft.rulesets) == rulesets_before
    assert LanLedger(paths.state / "lan").sessions() == []
    assert capsys.readouterr().err.startswith("guest-firewall:")


def test_lan_open_that_nft_refuses_leaves_nothing_recorded_and_says_why(container, capsys):
    run, nft, paths, _ = container
    run("init")
    nft.returncode = 1

    assert run("lan-open", stdin=session_json()) == 1

    assert LanLedger(paths.state / "lan").sessions() == []
    assert "nft refused" in capsys.readouterr().err


def test_a_program_that_cannot_run_is_a_failure_with_a_message_not_a_traceback(container, capsys):
    run, _nft, _paths, programs = container
    run("init")

    def timing_out(args, timeout=None):
        raise MediaProblem(Fault.TIMED_OUT, detail=args[0])

    programs.nft = timing_out

    assert run("lan-open", stdin=session_json()) == 1

    assert capsys.readouterr().err == "guest-firewall: nft did not run (timed_out)\n"


def test_lan_close_removes_what_the_session_needed_and_prints_nothing(container, capsys):
    run, nft, paths, _ = container
    run("init")
    run("lan-open", stdin=session_json())

    assert run("lan-close", "task-1") == 0

    assert LanLedger(paths.state / "lan").sessions() == []
    assert nft.state() == ([], {"INPUT": [], "OUTPUT": []}, {})
    assert capsys.readouterr() == ("", "")


def test_lan_close_of_a_session_that_is_not_open_is_not_an_error(container):
    run, _nft, _paths, _ = container
    run("init")

    assert run("lan-close", "task-9") == 0


def test_lan_close_of_a_key_that_is_not_a_key_fails(container, capsys):
    run, _nft, _paths, _ = container
    run("init")

    assert run("lan-close", "../../etc") == 1
    assert capsys.readouterr().err.startswith("guest-firewall:")


def test_lan_close_before_init_fails_loudly(container):
    run, _nft, _paths, _ = container

    assert run("lan-close", "task-1") == 1


def test_lan_list_prints_the_open_keys_one_per_line_in_order(container, capsys):
    run, _nft, _paths, _ = container
    run("init")
    run("lan-open", stdin=session_json(SESSION_B_ON_LAB1))
    run("lan-open", stdin=session_json())
    capsys.readouterr()

    assert run("lan-list") == 0

    assert capsys.readouterr().out == "task-1\ntask-2\n"


def test_lan_list_of_no_session_prints_nothing(container, capsys):
    run, _nft, _paths, _ = container
    run("init")

    assert run("lan-list") == 0
    assert capsys.readouterr().out == ""


@pytest.mark.parametrize(
    "arguments",
    [("lan-open", "extra"), ("lan-close",), ("lan-close", "a", "b"), ("lan-list", "x")],
)
def test_the_lan_commands_with_the_wrong_arguments_are_usage_errors(container, arguments):
    run, _nft, _paths, _ = container

    assert run(*arguments) == 2


@pytest.mark.parametrize("arguments", [("lan-open",), ("lan-close", "task-1"), ("lan-list",)])
def test_every_lan_command_takes_the_lock_the_hook_takes(container, monkeypatch, arguments):
    run, _nft, _paths, _ = container
    run("init")
    locked: list[int] = []
    monkeypatch.setattr(
        guest_firewall.fcntl, "flock", lambda _file, operation: locked.append(operation)
    )

    run(*arguments, stdin=session_json())

    assert locked == [guest_firewall.fcntl.LOCK_EX]
