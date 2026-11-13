"""Tests of `bin/container-egress`, the command the entrypoint runs before any program starts."""

import pytest
from test_control_http import load_script
from test_guest_firewall import ROUTES, Nft

container_egress = load_script("container-egress")

ENVIRONMENT = {"CAPE_DB_IP": "172.20.0.3", "CAPE_DB_IFACE": "eth0"}


@pytest.fixture
def container(tmp_path):
    nft = Nft()
    rules = tmp_path / "state" / "egress.nft"

    def run(*arguments, environ=ENVIRONMENT, routes=ROUTES):
        this = container_egress.Container(rules, nft, lambda: routes, environ)
        return container_egress.main(list(arguments), this)

    return run, nft, rules


def test_init_applies_the_egress_ruleset_found_from_the_environment_and_the_routes(container):
    run, nft, rules = container

    assert run("init") == 0

    assert "meta skuid cape ip daddr 172.20.0.0/16 tcp dport 5432 accept" in nft.rulesets[-1]
    assert nft.rulesets[-1] == rules.read_text()


def test_the_rules_file_is_private_to_root(container):
    run, _nft, rules = container
    run("init")

    assert rules.stat().st_mode & 0o777 == 0o600


def test_a_ruleset_nft_refuses_is_a_failure_the_entrypoint_sees(container, capsys):
    run, nft, _ = container
    nft.returncode = 1

    assert run("init") == 1
    assert "container-egress:" in capsys.readouterr().err


def test_an_environment_without_the_database_network_is_a_failure_and_applies_nothing(container):
    run, nft, _ = container

    assert run("init", environ={}) == 1
    assert nft.rulesets == []


@pytest.mark.parametrize("arguments", [[], ["hook"], ["init", "extra"]])
def test_anything_but_init_is_a_usage_error(container, arguments):
    run, nft, _ = container

    assert run(*arguments) == container_egress.USAGE_ERROR
    assert nft.rulesets == []
