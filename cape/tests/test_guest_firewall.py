"""What a guest on `tt-guest` may reach, and as whom: the nftables ruleset the container applies,
the networks it keeps guests out of, and the libvirt hook that binds a guest's port to its address.

CAPE's rooter inserts its FORWARD jumps again at every start with its accept chain first, and its
rules match only a guest's source address; a guest that takes another address, or reaches the
container's own listeners, escapes both. These rules live in a table of their own, at a priority
before iptables' chains, so neither the rooter's order nor its cleanup touches them.
"""

import json
from pathlib import Path

import pytest
from fixtures.guest_samples import make_guest

from guest_engine.firewall import (
    FirewallPolicy,
    GuestFirewall,
    GuestPort,
    PortLedger,
    load_policy,
    networks_behind,
    policy_for,
    ports_in,
    render_ruleset,
    store_policy,
)
from guest_engine.media import CommandResult
from guest_engine.registry import Registry

GATEWAY = "192.168.150.1"
SUBNET = "192.168.150.0/24"
POLICY = FirewallPolicy(
    bridge="tt-guest", gateway=GATEWAY, subnet=SUBNET, networks=("172.19.0.0/16", "172.18.0.0/16")
)
LAB1 = GuestPort(domain="lab1", tap="vnet10", mac="00:14:22:8d:44:27")
W10 = GuestPort(domain="w10-q", tap="vnet11", mac="00:14:22:fe:83:09")
ADDRESSES = {"lab1": "192.168.150.11", "w10-q": "192.168.150.12"}


def section(ruleset: str, name: str) -> str:
    """The text of one `chain` or `set` block, so a test reads only the part it is about."""
    start = ruleset.index(f"{name} {{")
    return ruleset[start : ruleset.index("\n    }", start)]


def rendered(ports=(LAB1, W10), addresses=ADDRESSES, policy=POLICY) -> str:
    return render_ruleset(policy, ports, addresses)


# --- what a guest may reach on the container -----------------------------------------------------


def test_a_guest_may_reach_the_gateway_and_nothing_else_on_the_container():
    chain = section(rendered(), "chain input")

    assert f"ip daddr {GATEWAY} accept" in chain
    assert chain.rstrip().endswith("drop")
    assert chain.index(f"ip daddr {GATEWAY}") < chain.rindex("drop")


def test_dhcp_discovery_reaches_dnsmasq_though_it_is_not_addressed_to_the_gateway():
    assert "ip daddr 255.255.255.255 udp dport 67 accept" in section(rendered(), "chain input")


def test_traffic_that_does_not_come_from_the_guest_bridge_is_left_alone():
    ruleset = rendered()

    assert 'iifname != "tt-guest" return' in section(ruleset, "chain input")
    assert 'iifname != "tt-guest" return' in section(ruleset, "chain forward")


def test_the_rules_run_before_iptables_whatever_order_the_rooter_leaves_its_jumps_in():
    ruleset = rendered()

    assert "hook input priority -10" in ruleset
    assert "hook forward priority -10" in ruleset


# --- what a guest may reach through the container ------------------------------------------------


def test_a_guest_cannot_reach_another_guest_through_the_gateway():
    chain = section(rendered(), "chain forward")

    assert 'oifname "tt-guest" counter drop' in chain
    assert chain.index('oifname "tt-guest"') < chain.index("@unreachable")


def test_the_networks_the_container_is_on_are_unreachable_with_the_private_ranges():
    unreachable = section(rendered(), "set unreachable")

    for network in (
        "172.19.0.0/16",
        "172.18.0.0/16",
        "10.0.0.0/8",
        "172.16.0.0/12",
        "192.168.0.0/16",
        "169.254.0.0/16",
        "100.64.0.0/10",
        "127.0.0.0/8",
    ):
        assert network in unreachable


def test_unreachable_destinations_are_refused_before_the_rooters_accept_can_see_them():
    chain = section(rendered(), "chain forward")

    assert "ip daddr @unreachable counter reject" in chain


def test_nothing_forwards_over_ipv6():
    assert "meta nfproto ipv6 counter drop" in section(rendered(), "chain forward")


# --- who a guest may be --------------------------------------------------------------------------


def test_each_port_is_bound_to_the_mac_of_its_guest():
    macs = section(rendered(), "set port_macs")

    assert '"vnet10" . 00:14:22:8d:44:27' in macs
    assert '"vnet11" . 00:14:22:fe:83:09' in macs


def test_a_frame_from_a_port_that_is_not_bound_is_dropped():
    chain = section(rendered(), "chain from_guest")

    assert "policy drop" in chain
    assert "iifname . ether saddr @port_macs jump checked" in chain


def test_a_registered_address_belongs_to_the_port_of_its_guest_only():
    ruleset = rendered()

    assert '"vnet10" . 00:14:22:8d:44:27 . 192.168.150.11' in section(ruleset, "set bound")
    assert '"vnet11" . 00:14:22:fe:83:09 . 192.168.150.12' in section(ruleset, "set bound")
    assert "ip saddr @protected iifname . ether saddr . ip saddr @bound accept" in ruleset
    assert "ip saddr @protected counter drop" in ruleset


def test_the_gateway_and_the_addresses_of_running_guests_are_protected():
    protected = section(rendered(), "set protected")

    assert GATEWAY in protected
    assert "192.168.150.11" in protected
    assert "192.168.150.12" in protected


def test_the_address_of_a_guest_that_is_not_running_is_not_protected():
    protected = section(rendered(ports=(LAB1,)), "set protected")

    assert "192.168.150.11" in protected
    assert "192.168.150.12" not in protected


def test_a_guest_without_a_record_has_a_port_but_no_address_to_claim():
    ruleset = rendered(addresses={"w10-q": "192.168.150.12"})

    assert '"vnet10" . 00:14:22:8d:44:27' in section(ruleset, "set port_macs")
    assert "00:14:22:8d:44:27 . 192" not in section(ruleset, "set bound")


def test_a_source_address_outside_the_guest_subnet_is_dropped():
    ruleset = rendered()

    assert f"ip saddr != {SUBNET} counter drop" in section(ruleset, "chain ip_from_guest")
    assert f"arp saddr ip != {SUBNET} counter drop" in section(ruleset, "chain arp_from_guest")


def test_an_arp_sender_that_is_not_the_mac_of_the_port_is_dropped():
    chain = section(rendered(), "chain arp_from_guest")

    assert "iifname . arp saddr ether != @port_macs counter drop" in chain


def test_dhcp_discovery_from_the_unspecified_address_is_allowed_and_other_traffic_from_it_is_not():
    chain = section(rendered(), "chain ip_from_guest")

    assert "ip saddr 0.0.0.0 udp sport 68 udp dport 67 accept" in chain
    assert "ip saddr 0.0.0.0 counter drop" in chain


def test_arp_probes_from_the_unspecified_address_are_allowed():
    assert "arp saddr ip 0.0.0.0 accept" in section(rendered(), "chain arp_from_guest")


def test_the_ruleset_replaces_the_previous_one_in_a_single_transaction():
    lines = rendered().splitlines()

    for family in ("inet", "bridge"):
        declare = lines.index(f"table {family} tartarus_guest")
        assert lines[declare + 1] == f"delete table {family} tartarus_guest"
        assert lines[declare + 2] == f"table {family} tartarus_guest {{"


@pytest.mark.parametrize(
    "port",
    [
        GuestPort("x", 'vnet0" ; flush ruleset ; "', "00:14:22:8d:44:27"),
        GuestPort("x", "vnet0", "00:14:22:8d:44"),
        GuestPort("x", "", "00:14:22:8d:44:27"),
    ],
)
def test_a_port_that_is_not_an_interface_name_and_a_mac_never_reaches_the_ruleset(port):
    with pytest.raises(ValueError, match="port"):
        rendered(ports=(port,))


def test_an_address_that_is_not_ipv4_never_reaches_the_ruleset():
    with pytest.raises(ValueError, match="address"):
        rendered(addresses={"lab1": "1.1.1.1 } ; flush ruleset ; {"})


# --- the networks the container is on ------------------------------------------------------------

ROUTES = """\
default via 172.19.0.1 dev eth2
172.18.0.0/16 dev eth1 proto kernel scope link src 172.18.0.2
172.19.0.0/16 dev eth2 proto kernel scope link src 172.19.0.2
172.20.0.0/16 dev eth0 proto kernel scope link src 172.20.0.3
192.168.150.0/24 dev tt-guest proto kernel scope link src 192.168.150.1 linkdown
"""


def test_every_network_the_container_is_on_is_found_except_the_guest_bridge():
    assert networks_behind(ROUTES, bridge="tt-guest") == [
        "172.19.0.1/32",
        "172.18.0.0/16",
        "172.19.0.0/16",
        "172.20.0.0/16",
    ]


def test_routes_that_are_not_ipv4_networks_are_skipped():
    assert (
        networks_behind("unreachable fe80::/64 dev lo\nbroadcast 1.2.3.4 dev lo\n", "tt-guest")
        == []
    )


# --- the libvirt hook ----------------------------------------------------------------------------

STARTED_XML = """\
<domain type='kvm' id='7'>
  <name>lab1</name>
  <devices>
    <interface type='network'>
      <mac address='00:14:22:8D:44:27'/>
      <source network='tt-guest' portid='abc' bridge='tt-guest'/>
      <target dev='vnet10'/>
      <model type='e1000e'/>
    </interface>
    <interface type='network'>
      <mac address='52:54:00:00:00:01'/>
      <source network='default' bridge='virbr0'/>
      <target dev='vnet11'/>
    </interface>
  </devices>
</domain>
"""


def test_the_ports_of_a_started_domain_are_those_on_the_guest_bridge_with_lowercase_macs():
    assert ports_in(STARTED_XML, bridge="tt-guest") == [
        GuestPort(domain="lab1", tap="vnet10", mac="00:14:22:8d:44:27")
    ]


def test_an_interface_that_has_no_target_yet_is_not_a_port():
    xml = STARTED_XML.replace("<target dev='vnet10'/>", "")

    assert ports_in(xml, bridge="tt-guest") == []


class Nft:
    """Records the rulesets the firewall hands to nft."""

    def __init__(self):
        self.rulesets: list[str] = []
        self.returncode = 0

    def __call__(self, args, timeout=None):
        assert args[:2] == ["nft", "-f"]
        self.rulesets.append(Path(args[2]).read_text())
        return CommandResult(self.returncode, "", "boom" if self.returncode else "")


@pytest.fixture
def firewall(tmp_path):
    registry = Registry(tmp_path / "guests")
    registry.create(make_guest("lab1", "192.168.150.11"))
    nft = Nft()
    ledger = PortLedger(tmp_path / "ports")
    return (
        GuestFirewall(
            policy=POLICY,
            ledger=ledger,
            registry=registry,
            runner=nft,
            rules_file=tmp_path / "rules.nft",
        ),
        nft,
        ledger,
    )


def test_a_started_guest_is_bound_before_it_is_used(firewall):
    guard, nft, _ = firewall

    guard.hook("lab1", "started", STARTED_XML)

    assert '"vnet10" . 00:14:22:8d:44:27 . 192.168.150.11' in nft.rulesets[-1]


def test_a_stopped_guest_loses_its_binding(firewall):
    guard, nft, _ = firewall
    guard.hook("lab1", "started", STARTED_XML)

    guard.hook("lab1", "stopped", "")

    assert "vnet10" not in nft.rulesets[-1]
    assert "192.168.150.11" not in section(nft.rulesets[-1], "set protected")


def test_a_released_guest_loses_its_binding_too(firewall):
    guard, nft, _ = firewall
    guard.hook("lab1", "started", STARTED_XML)

    guard.hook("lab1", "release", "")

    assert "vnet10" not in nft.rulesets[-1]


@pytest.mark.parametrize("operation", ["prepare", "start", "migrate", "restore", "reconnect"])
def test_other_events_change_nothing(firewall, operation):
    guard, nft, _ = firewall

    guard.hook("lab1", operation, STARTED_XML)

    assert nft.rulesets == []


def test_two_guests_are_bound_side_by_side(firewall):
    guard, nft, _ = firewall
    guard.hook("lab1", "started", STARTED_XML)
    other = (
        STARTED_XML.replace("lab1", "w10-q")
        .replace("vnet10", "vnet12")
        .replace("00:14:22:8D:44:27", "00:14:22:FE:83:09")
    )

    guard.hook("w10-q", "started", other)

    assert '"vnet10" . 00:14:22:8d:44:27' in nft.rulesets[-1]
    assert '"vnet12" . 00:14:22:fe:83:09' in nft.rulesets[-1]


def test_initialising_forgets_ports_of_a_previous_life_and_applies_the_ruleset(firewall):
    guard, nft, ledger = firewall
    ledger.record("lab1", [LAB1])

    guard.initialise()

    assert ledger.ports() == []
    assert "vnet10" not in nft.rulesets[-1]
    assert f"ip daddr {GATEWAY} accept" in nft.rulesets[-1]


def test_a_ruleset_nft_refuses_is_an_error_not_a_silent_open_door(firewall):
    guard, nft, _ = firewall
    nft.returncode = 1

    with pytest.raises(RuntimeError, match="nft"):
        guard.hook("lab1", "started", STARTED_XML)


def test_the_ledger_survives_a_corrupt_file_by_forgetting_that_guest(tmp_path):
    ledger = PortLedger(tmp_path)
    ledger.record("lab1", [LAB1])
    (tmp_path / "lab1.json").write_text("{not json")
    ledger.record("w10-q", [W10])

    assert ledger.ports() == [W10]


def test_the_ledger_writes_one_file_per_domain(tmp_path):
    ledger = PortLedger(tmp_path)

    ledger.record("lab1", [LAB1])

    assert json.loads((tmp_path / "lab1.json").read_text()) == [
        {"domain": "lab1", "tap": "vnet10", "mac": "00:14:22:8d:44:27"}
    ]


def test_a_domain_name_cannot_walk_out_of_the_ledger_directory(tmp_path):
    with pytest.raises(ValueError, match="domain"):
        PortLedger(tmp_path / "ports").record("../escape", [LAB1])


# --- the policy of this container ----------------------------------------------------------------


def test_the_policy_is_stored_for_the_hook_which_has_no_environment_of_its_own(tmp_path):
    store_policy(tmp_path, POLICY)

    assert load_policy(tmp_path) == POLICY


def test_the_policy_comes_from_the_guest_subnet_and_the_routes_of_the_container():
    policy = policy_for({"GUEST_SUBNET": "192.168.77.0/24"}, ROUTES, "tt-guest", "192.168.150.0/24")

    assert policy.gateway == "192.168.77.1"
    assert policy.subnet == "192.168.77.0/24"
    assert "172.19.0.0/16" in policy.networks
    assert not any(network.startswith("192.168.150.") for network in policy.networks)


def test_the_gateway_the_entrypoint_derived_wins_over_the_first_address():
    policy = policy_for(
        {"GUEST_GATEWAY_IP": "192.168.150.1"}, ROUTES, "tt-guest", "192.168.150.0/24"
    )

    assert policy.gateway == "192.168.150.1"
    assert policy.subnet == "192.168.150.0/24"


def test_a_subnet_that_is_not_ipv4_is_refused():
    with pytest.raises(ValueError, match="IPv4"):
        policy_for({"GUEST_SUBNET": "fd00::/64"}, ROUTES, "tt-guest", "192.168.150.0/24")
