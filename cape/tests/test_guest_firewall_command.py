"""Tests of `bin/guest-firewall`, the command the entrypoint and libvirt's qemu hook run."""

import json

import pytest
from fixtures.guest_samples import make_guest
from test_control_http import load_script
from test_guest_firewall import ROUTES, STARTED_XML, Nft
from test_port_isolation import Bridge

from guest_engine.firewall import PortLedger
from guest_engine.registry import Registry

guest_firewall = load_script("guest-firewall")

ENVIRONMENT = {"GUEST_SUBNET": "192.168.150.0/24", "GUEST_GATEWAY_IP": "192.168.150.1"}


class Programs:
    """The container's programs: `bridge` and `nft`, with the order they were called in."""

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
    nft = Nft()
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
