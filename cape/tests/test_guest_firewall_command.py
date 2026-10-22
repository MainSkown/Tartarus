"""Tests of `bin/guest-firewall`, the command the entrypoint and libvirt's qemu hook run."""

import json

import pytest
from fixtures.guest_samples import make_guest
from test_control_http import load_script
from test_guest_firewall import ROUTES, STARTED_XML, Nft

from guest_engine.firewall import PortLedger
from guest_engine.registry import Registry

guest_firewall = load_script("guest-firewall")

ENVIRONMENT = {"GUEST_SUBNET": "192.168.150.0/24", "GUEST_GATEWAY_IP": "192.168.150.1"}


@pytest.fixture
def container(tmp_path):
    registry = Registry(tmp_path / "guests")
    registry.create(make_guest("lab1", "192.168.150.11"))
    nft = Nft()
    paths = guest_firewall.Paths(
        state=tmp_path / "state",
        registry=tmp_path / "guests",
        rules=tmp_path / "state" / "rules.nft",
    )

    def run(*arguments, environ=ENVIRONMENT, stdin=""):
        this = guest_firewall.Container(paths, nft, lambda: ROUTES, environ)
        return guest_firewall.main(list(arguments), stdin, this)

    return run, nft, paths


def test_init_stores_the_policy_it_found_and_applies_a_ruleset_with_no_bound_port(container):
    run, nft, paths = container

    assert run("init") == 0

    stored = json.loads((paths.state / "policy.json").read_text())
    assert stored["gateway"] == "192.168.150.1"
    assert "172.19.0.0/16" in stored["networks"]
    assert "vnet" not in nft.rulesets[-1]


def test_the_hook_binds_a_started_guest_using_the_policy_init_stored(container):
    run, nft, _paths = container
    run("init")

    assert run("hook", "lab1", "started", "begin", "-", environ={}, stdin=STARTED_XML) == 0

    assert '"vnet10" . 00:14:22:8d:44:27 . 192.168.150.11' in nft.rulesets[-1]


def test_the_hook_unbinds_a_stopped_guest(container):
    run, nft, paths = container
    run("init")
    run("hook", "lab1", "started", "begin", "-", environ={}, stdin=STARTED_XML)

    assert run("hook", "lab1", "stopped", "end", "-", environ={}) == 0

    assert "vnet10" not in nft.rulesets[-1]
    assert PortLedger(paths.state / "ports").ports() == []


def test_the_hook_before_init_fails_loudly_rather_than_applying_a_guess(container):
    run, nft, _ = container

    assert run("hook", "lab1", "started", "begin", "-", environ={}, stdin=STARTED_XML) == 1
    assert nft.rulesets == []


def test_a_ruleset_nft_refuses_is_a_failure_the_caller_sees(container):
    run, nft, _ = container
    nft.returncode = 1

    assert run("init") == 1


def test_an_unknown_command_is_a_usage_error(container):
    run, _, _ = container

    assert run("explode") == 2
    assert run() == 2
