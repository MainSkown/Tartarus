"""What the processes inside the cape container may connect to, as an nftables ruleset."""

import pytest
from test_guest_firewall import ROUTES

from guest_engine.egress import EgressPolicy, policy_for, render_egress_ruleset
from guest_engine.firewall import RESERVED_NETWORKS

ENVIRONMENT = {"CAPE_DB_IP": "172.20.0.3", "CAPE_DB_IFACE": "eth0"}


def make_policy(**changes) -> EgressPolicy:
    fields = {
        "bridge": "tt-guest",
        "cape_user": "cape",
        "database_network": "172.20.0.0/16",
        "networks": ("172.18.0.0/16", "172.19.0.0/16", "172.19.0.1/32"),
    }
    return EgressPolicy(**{**fields, **changes})


def output_rules(ruleset: str) -> list[str]:
    """The rules of the output chain, in order, without the hook line."""
    lines = ruleset.splitlines()
    start = lines.index("    chain output {")
    body = lines[start + 1 : lines.index("    }", start)]
    return [line.strip() for line in body if "hook output" not in line]


def test_the_table_is_replaced_whole_so_applying_it_twice_is_the_same_as_once():
    header = render_egress_ruleset(make_policy()).splitlines()[:3]

    assert header == [
        "table inet tartarus_egress",
        "delete table inet tartarus_egress",
        "table inet tartarus_egress {",
    ]


def test_the_chain_hooks_output_with_default_deny_before_iptables():
    ruleset = render_egress_ruleset(make_policy())

    assert "type filter hook output priority -10; policy drop;" in ruleset


def test_loopback_is_open_to_every_user():
    assert 'oifname "lo" accept' in output_rules(render_egress_ruleset(make_policy()))


def test_replies_on_connections_others_opened_are_accepted():
    assert "ct state established,related accept" in output_rules(
        render_egress_ruleset(make_policy())
    )


def test_anything_leaving_through_the_guest_bridge_is_accepted_for_every_user():
    rules = output_rules(render_egress_ruleset(make_policy(bridge="tt-lab")))

    assert 'oifname "tt-lab" accept' in rules


def test_cape_reaches_the_database_port_of_the_database_network_and_nothing_else():
    rules = output_rules(render_egress_ruleset(make_policy()))

    cape_rules = [rule for rule in rules if "skuid cape" in rule]
    assert cape_rules == ["meta skuid cape ip daddr 172.20.0.0/16 tcp dport 5432 accept"]


def test_root_reaches_https_on_public_addresses_only():
    rules = output_rules(render_egress_ruleset(make_policy()))

    root_rules = [rule for rule in rules if "skuid 0" in rule]
    assert root_rules == ["meta skuid 0 ip daddr != @not_public tcp dport 443 accept"]


def test_the_non_public_set_holds_every_reserved_range_and_every_network_the_container_is_on():
    ruleset = render_egress_ruleset(make_policy())
    elements = next(line for line in ruleset.splitlines() if "elements" in line)

    for network in (*RESERVED_NETWORKS, "172.18.0.0/16", "172.19.0.0/16", "172.19.0.1/32"):
        assert network in elements


def test_everything_else_is_rejected_last_and_counted():
    rules = output_rules(render_egress_ruleset(make_policy()))

    assert rules[-1] == "counter reject"
    assert rules.count("counter reject") == 1


def test_no_rule_lets_a_user_other_than_cape_or_root_out_except_through_the_open_flows():
    rules = output_rules(render_egress_ruleset(make_policy()))

    assert [rule for rule in rules if "skuid" not in rule] == [
        'oifname "lo" accept',
        "ct state established,related accept",
        'oifname "tt-guest" accept',
        "counter reject",
    ]


@pytest.mark.parametrize(
    "changes",
    [
        {"bridge": 'tt"; accept; "'},
        {"bridge": ""},
        {"cape_user": "cape accept"},
        {"cape_user": "0"},
        {"database_network": "not-a-network"},
        {"database_network": "0.0.0.0/0"},
        {"database_network": "8.8.8.0/24"},
        {"networks": ("172.19.0.0/16; accept",)},
    ],
)
def test_a_value_that_is_not_what_its_name_says_never_reaches_nft(changes):
    with pytest.raises(ValueError, match=r"."):
        render_egress_ruleset(make_policy(**changes))


def test_the_policy_is_found_from_the_database_address_and_the_routes():
    policy = policy_for(ENVIRONMENT, ROUTES, "tt-guest", "cape")

    assert policy.database_network == "172.20.0.0/16"
    assert policy.cape_user == "cape"
    assert policy.bridge == "tt-guest"
    assert "172.18.0.0/16" in policy.networks
    assert "192.168.150.0/24" not in policy.networks


@pytest.mark.parametrize(
    "environ",
    [
        {},
        {"CAPE_DB_IP": "172.20.0.3"},
        {"CAPE_DB_IP": "", "CAPE_DB_IFACE": "eth0"},
        {"CAPE_DB_IP": "172.20.0.3", "CAPE_DB_IFACE": "eth9"},
        {"CAPE_DB_IP": "172.18.0.9", "CAPE_DB_IFACE": "eth0"},
        {"CAPE_DB_IP": "not-an-address", "CAPE_DB_IFACE": "eth0"},
    ],
)
def test_a_database_network_that_cannot_be_found_is_an_error_not_a_guess(environ):
    with pytest.raises(ValueError, match=r"CAPE_DB|database"):
        policy_for(environ, ROUTES, "tt-guest", "cape")


def test_the_default_route_is_never_taken_for_the_database_network():
    routes = "default via 172.20.0.1 dev eth0\n"

    with pytest.raises(ValueError, match="database"):
        policy_for(ENVIRONMENT, routes, "tt-guest", "cape")
