"""The fake local network's share of the guest firewall: what a guest may reach in the address block
while a session is open, and the iptables rules, local routes and nft tables that go with it.

Nothing is rendered or added while no session exists; the no-session ruleset is the one
`test_guest_firewall.py` pins byte for byte.
"""

import json
import re
import shlex
import shutil
import subprocess
from pathlib import Path

import pytest
from fixtures.guest_samples import make_guest
from test_guest_firewall import ADDRESSES, LAB1, POLICY, STARTED_XML, W10, rendered, section

from guest_engine.firewall import FirewallPolicy, GuestFirewall, PortLedger, render_ruleset
from guest_engine.lan_firewall import (
    LAN_COMMENT,
    LAN_ROUTE_PROTOCOL,
    LanLedger,
    LanSession,
    LanTarget,
)
from guest_engine.media import CommandResult, MediaProblem
from guest_engine.media.errors import Fault
from guest_engine.registry import Registry

FIXTURES = Path(__file__).parent / "fixtures"
NFT, UNSHARE = shutil.which("nft"), shutil.which("unshare")
GUEST_A, GUEST_B = ADDRESSES["lab1"], ADDRESSES["w10-q"]
DC, FILE_SERVER, PRINTER = "192.168.150.200", "192.168.150.201", "192.168.150.202"
BLOCK = "192.168.150.200-192.168.150.247"
SESSION_A = LanSession(
    "task-1", GUEST_A, (LanTarget(DC, (445, 3389)), LanTarget(FILE_SERVER, (445,)))
)
SESSION_B = LanSession("task-2", GUEST_B, (LanTarget(PRINTER, (9100,)),))
OUTPUT_ACCEPT = (
    f"-d {GUEST_A}/32 -m iprange --src-range {BLOCK} -m comment --comment {LAN_COMMENT} -j ACCEPT"
)
INPUT_ACCEPT = (
    f"-s {GUEST_A}/32 -m iprange --dst-range {BLOCK} -m comment --comment {LAN_COMMENT} -j ACCEPT"
)
ROOTER_RULE = f"-s {GUEST_A}/32 -p tcp -m tcp --dport 22 -m comment --comment CAPE-rooter -j DROP"
FOREIGN_RULE = "-s 10.1.1.1/32 -j DROP"


def lan_ruleset(*sessions: LanSession, policy: FirewallPolicy = POLICY) -> str:
    return render_ruleset(policy, (LAB1, W10), ADDRESSES, lan_sessions=sessions)


def elements(ruleset: str, name: str) -> set[str]:
    block = section(ruleset, f"set {name}")
    marker = "elements = {"
    if marker not in block:
        return set()
    listed = block[block.index(marker) + len(marker) : block.index("}", block.index(marker))]
    return {item.strip() for item in listed.split(",") if item.strip()}


# --- a session is made of validated values --------------------------------------------------------


@pytest.mark.parametrize(
    "key",
    ["", "a b", "a;b", "a\nb", "a}b", "-leading-dash", "x" * 65, "../escape", "ü", "a/b", "a.b"],
)
def test_a_key_that_is_not_letters_digits_and_dashes_is_refused(key):
    with pytest.raises(ValueError, match="key"):
        LanSession(key, GUEST_A, ())


@pytest.mark.parametrize("key", ["1", "task-17", "A" * 64, "0a-b-c"])
def test_a_key_of_letters_digits_and_dashes_is_accepted(key):
    assert LanSession(key, GUEST_A, ()).key == key


ADDRESS_INJECTIONS = [
    "192.168.150.200\n",
    "192.168.150.200; drop",
    "192.168.150.200 }",
    "1.2.3.4}\ndelete table inet tartarus_guest",
    "not-an-ip",
    "::1",
    "300.1.1.1",
    "192.168.150.0/24",
    "192.168.150.200-192.168.150.247",
    "",
    3232273000,
    None,
]


@pytest.mark.parametrize("address", ADDRESS_INJECTIONS)
def test_a_guest_address_that_is_not_an_ipv4_address_is_refused(address):
    with pytest.raises(ValueError, match="address"):
        LanSession("task-1", address, ())


@pytest.mark.parametrize("address", ADDRESS_INJECTIONS)
def test_a_target_address_that_is_not_an_ipv4_address_is_refused(address):
    with pytest.raises(ValueError, match="address"):
        LanTarget(address, (445,))


@pytest.mark.parametrize("port", [0, -1, 65536, 70000, True, "445", 445.0, None])
def test_a_port_outside_1_to_65535_or_not_an_integer_is_refused(port):
    with pytest.raises(ValueError, match="port"):
        LanTarget(DC, (445, port))


@pytest.mark.parametrize("port", [1, 445, 65535])
def test_the_ends_of_the_port_range_are_accepted(port):
    assert LanTarget(DC, (port,)).tcp_ports == (port,)


def test_a_session_whose_targets_were_slipped_in_unvalidated_is_refused_at_render():
    session = LanSession("task-1", GUEST_A, ())
    object.__setattr__(session, "targets", (LanTarget.__new__(LanTarget),))

    with pytest.raises((ValueError, AttributeError)):
        lan_ruleset(session)


@pytest.mark.parametrize(
    "target",
    [
        "192.168.150.1",
        "192.168.150.199",
        "192.168.150.248",
        "192.168.150.10",
        "172.19.0.2",
        "127.0.0.1",
    ],
)
def test_a_target_outside_the_address_block_never_reaches_the_ruleset(target):
    session = LanSession("task-1", GUEST_A, (LanTarget(target, (80,)),))

    with pytest.raises(ValueError, match="block"):
        lan_ruleset(session)


@pytest.mark.parametrize("guest", ["192.168.150.200", "192.168.150.247", "10.9.9.9", "172.19.0.2"])
def test_a_guest_inside_the_block_or_outside_the_subnet_is_refused(guest):
    session = LanSession("task-1", guest, (LanTarget(DC, (445,)),))

    with pytest.raises(ValueError, match="guest"):
        lan_ruleset(session)


# --- the input chain ------------------------------------------------------------------------------


def test_with_no_session_the_lan_arguments_change_nothing():
    assert lan_ruleset() == rendered()
    assert "lan_tcp" not in rendered()


def test_one_session_opens_exactly_its_pairs_and_ports_in_the_input_chain():
    ruleset = lan_ruleset(SESSION_A)

    assert elements(ruleset, "lan_tcp") == {
        f"{GUEST_A} . {DC} . 445",
        f"{GUEST_A} . {DC} . 3389",
        f"{GUEST_A} . {FILE_SERVER} . 445",
    }
    assert elements(ruleset, "lan_icmp") == {f"{GUEST_A} . {DC}", f"{GUEST_A} . {FILE_SERVER}"}


def test_the_pairs_are_accepted_after_replies_and_before_the_final_drop():
    chain = section(lan_ruleset(SESSION_A), "chain input")
    tcp_rule = "ip saddr . ip daddr . tcp dport @lan_tcp accept"
    icmp_rule = "ip saddr . ip daddr @lan_icmp icmp type echo-request accept"

    assert chain.index("ct state established,related accept") < chain.index(tcp_rule)
    assert chain.index(tcp_rule) < chain.index(icmp_rule) < chain.index("counter drop")
    assert chain.rstrip().endswith("counter drop")


def test_the_rest_of_the_input_chain_is_what_it_was_without_a_session():
    without = section(rendered(), "chain input").splitlines()
    with_session = section(lan_ruleset(SESSION_A), "chain input").splitlines()

    assert [line for line in with_session if "@lan_" not in line] == without


def test_two_sessions_open_each_guests_own_pairs_and_never_the_others():
    ruleset = lan_ruleset(SESSION_A, SESSION_B)
    tcp = elements(ruleset, "lan_tcp")
    icmp = elements(ruleset, "lan_icmp")

    assert f"{GUEST_B} . {PRINTER} . 9100" in tcp
    assert f"{GUEST_A} . {DC} . 445" in tcp
    assert not {pair for pair in tcp if pair.startswith(GUEST_A) and PRINTER in pair}
    assert not {
        pair for pair in tcp if pair.startswith(GUEST_B) and (DC in pair or FILE_SERVER in pair)
    }
    assert icmp == {f"{GUEST_A} . {DC}", f"{GUEST_A} . {FILE_SERVER}", f"{GUEST_B} . {PRINTER}"}


def test_a_host_with_no_tcp_port_may_be_pinged_and_nothing_else():
    ruleset = lan_ruleset(LanSession("task-1", GUEST_A, (LanTarget(DC, ()),)))

    assert elements(ruleset, "lan_tcp") == set()
    assert elements(ruleset, "lan_icmp") == {f"{GUEST_A} . {DC}"}


def test_a_session_with_no_target_opens_nothing_but_still_guards_the_block():
    ruleset = lan_ruleset(LanSession("task-1", GUEST_A, ()))

    assert elements(ruleset, "lan_tcp") == set()
    assert "ip saddr @fake_block counter drop" in ruleset


def test_the_elements_are_sorted_so_the_same_sessions_render_the_same_text():
    shuffled = LanSession(
        "task-1", GUEST_A, (LanTarget(FILE_SERVER, (445,)), LanTarget(DC, (3389, 445)))
    )

    assert lan_ruleset(shuffled) == lan_ruleset(SESSION_A)


# --- the bridge table -----------------------------------------------------------------------------


def bridge_part(ruleset: str) -> str:
    return ruleset[ruleset.index("table bridge tartarus_guest {") :]


def test_the_address_block_is_one_interval_set_taken_from_the_guest_subnet():
    assert elements(lan_ruleset(SESSION_A), "fake_block") == {BLOCK}

    other = FirewallPolicy(bridge="tt-guest", gateway="10.77.4.1", subnet="10.77.4.0/24")
    session = LanSession("task-1", "10.77.4.10", (LanTarget("10.77.4.200", (445,)),))
    ruleset = render_ruleset(other, (), {}, lan_sessions=(session,))

    assert elements(ruleset, "fake_block") == {"10.77.4.200-10.77.4.247"}
    assert "192.168.150" not in ruleset


def test_arp_and_ip_to_the_block_are_dropped_unless_the_pair_is_allowed():
    bridge = bridge_part(lan_ruleset(SESSION_A))

    assert (
        "arp daddr ip @fake_block arp saddr ip . arp daddr ip != @lan_pairs counter drop" in bridge
    )
    assert "ip daddr @fake_block ip saddr . ip daddr != @lan_pairs counter drop" in bridge
    assert elements(bridge, "lan_pairs") == {f"{GUEST_A} . {DC}", f"{GUEST_A} . {FILE_SERVER}"}


def test_a_frame_that_uses_an_address_of_the_block_as_its_source_is_dropped():
    bridge = bridge_part(lan_ruleset(SESSION_A))

    assert "arp saddr ip @fake_block counter drop" in bridge
    assert "ip saddr @fake_block counter drop" in bridge


def test_the_block_rules_run_before_any_accept_that_would_end_the_checks():
    arp = section(lan_ruleset(SESSION_A), "chain arp_from_guest")
    ip = section(lan_ruleset(SESSION_A), "chain ip_from_guest")

    assert arp.index("@fake_block") < arp.index("arp saddr ip 0.0.0.0 accept")
    assert arp.index("arp daddr ip @fake_block") < arp.index("@protected iifname")
    assert ip.index("ip saddr @fake_block") < ip.index("ip saddr @protected iifname")
    assert ip.index("ip daddr @fake_block") < ip.index("ip saddr @protected iifname")
    assert ip.index("udp sport 68 udp dport 67 accept") < ip.index("ip saddr @fake_block")


def test_the_bridge_gains_no_accept_a_pair_could_use_to_skip_the_spoofing_checks():
    def accepts(ruleset: str) -> list[str]:
        return [
            line.strip()
            for line in bridge_part(ruleset).splitlines()
            if line.strip().endswith("accept")
        ]

    assert accepts(lan_ruleset(SESSION_A, SESSION_B)) == accepts(rendered())


def test_the_bridge_sets_of_the_other_tables_do_not_leak_into_it():
    ruleset = lan_ruleset(SESSION_A)
    inet = ruleset[: ruleset.index("table bridge")]

    assert "lan_pairs" not in inet
    assert "lan_tcp" not in bridge_part(ruleset)


# --- the tables of ours ---------------------------------------------------------------------------


def test_the_raw_table_does_not_track_the_allowed_pairs_in_either_direction():
    ruleset = lan_ruleset(SESSION_A)
    raw = ruleset[ruleset.index("table ip tartarus_lan_raw {") :]
    raw = raw[: raw.index("\n}\n")]

    assert "hook prerouting priority -300" in raw
    assert "hook output priority -300" in raw
    assert 'iifname "tt-guest" ip saddr . ip daddr @lan_pairs notrack' in raw
    assert 'oifname "tt-guest" ip daddr . ip saddr @lan_pairs notrack' in raw
    assert elements(raw, "lan_pairs") == {f"{GUEST_A} . {DC}", f"{GUEST_A} . {FILE_SERVER}"}


def test_replies_from_a_fake_address_leave_with_the_ttl_of_a_lan_host():
    ruleset = lan_ruleset(SESSION_A)
    ttl = ruleset[ruleset.index("table ip tartarus_lan_ttl {") :]
    ttl = ttl[: ttl.index("\n}\n")]

    assert "type route hook output priority -150" in ttl
    assert 'oifname "tt-guest" ip saddr @fake_hosts ip ttl set 128' in ttl
    assert elements(ttl, "fake_hosts") == {DC, FILE_SERVER}


def test_both_tables_are_replaced_in_the_same_transaction_as_the_rest():
    ruleset = lan_ruleset(SESSION_A)

    for table in ("tartarus_lan_raw", "tartarus_lan_ttl"):
        assert f"table ip {table}\ndelete table ip {table}\ntable ip {table} {{" in ruleset


def test_with_no_session_neither_table_is_rendered():
    assert "tartarus_lan" not in lan_ruleset()


# --- the ledger -----------------------------------------------------------------------------------


def test_a_session_survives_a_round_trip_through_the_ledger(tmp_path):
    ledger = LanLedger(tmp_path)

    ledger.record(SESSION_A)
    ledger.record(SESSION_B)

    assert ledger.sessions() == [SESSION_A, SESSION_B]


def test_the_ledger_writes_one_file_per_session_key(tmp_path):
    LanLedger(tmp_path).record(SESSION_A)

    assert json.loads((tmp_path / "task-1.json").read_text()) == {
        "key": "task-1",
        "guest_address": GUEST_A,
        "targets": [
            {"address": DC, "tcp_ports": [445, 3389]},
            {"address": FILE_SERVER, "tcp_ports": [445]},
        ],
    }


def test_recording_a_key_again_replaces_that_session(tmp_path):
    ledger = LanLedger(tmp_path)
    ledger.record(SESSION_A)

    ledger.record(LanSession("task-1", GUEST_B, ()))

    assert ledger.sessions() == [LanSession("task-1", GUEST_B, ())]


def test_forgetting_a_session_removes_its_file_and_forgetting_twice_is_harmless(tmp_path):
    ledger = LanLedger(tmp_path)
    ledger.record(SESSION_A)

    ledger.forget("task-1")
    ledger.forget("task-1")

    assert ledger.sessions() == []
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(
    "content",
    [
        "{not json",
        "[]",
        "{}",
        '{"key": "x"}',
        '{"key":"a;b","guest_address":"1.2.3.4","targets":[]}',
        '{"key":"task-1","guest_address":"1.2.3.4}","targets":[]}',
        '{"key":"task-1","guest_address":"1.2.3.4","targets":[{"address":"1.2.3.5","tcp_ports":[0]}]}',
    ],
)
def test_an_unreadable_or_invalid_file_is_skipped_and_the_others_still_load(tmp_path, content):
    ledger = LanLedger(tmp_path)
    ledger.record(SESSION_B)
    (tmp_path / "broken.json").write_text(content)

    assert ledger.sessions() == [SESSION_B]


def test_clearing_the_ledger_forgets_every_session(tmp_path):
    ledger = LanLedger(tmp_path)
    ledger.record(SESSION_A)
    ledger.record(SESSION_B)

    ledger.clear()

    assert ledger.sessions() == []


def test_a_key_cannot_walk_out_of_the_ledger_directory(tmp_path):
    ledger = LanLedger(tmp_path / "lan")

    with pytest.raises(ValueError, match="key"):
        ledger.forget("../escape")


def test_a_missing_ledger_directory_holds_no_session(tmp_path):
    assert LanLedger(tmp_path / "never-created").sessions() == []


# --- applying: nft, iptables, routes --------------------------------------------------------------


class FakeContainer:
    """The programs the firewall drives in the container: `nft`, `iptables` and `ip`.

    `rulesets` is what was handed to `nft -f`; the tables, iptables chains and local routes are
    kept as state so a test reads what is there after an apply, and `changes` lists what the
    firewall ran that modifies it.
    """

    def __init__(self) -> None:
        self.rulesets: list[str] = []
        self.returncode = 0
        self.iptables_returncode = 0
        self.tables: set[str] = set()
        self.chains: dict[str, list[str]] = {"INPUT": [], "OUTPUT": []}
        self.routes: dict[str, str] = {}
        self.changes: list[list[str]] = []
        self.calls: list[list[str]] = []

    def __call__(self, args, timeout=None, stdin=None):
        self.calls.append(list(args))
        handlers = {"nft": self._nft, "iptables": self._iptables, "ip": self._ip}
        return handlers[args[0]](list(args))

    def _nft(self, args):
        if args[1] == "-f":
            if self.returncode:
                return CommandResult(self.returncode, "", "boom")
            self.rulesets.append(Path(args[2]).read_text())
            self.tables |= set(
                re.findall(r"^table ip (tartarus_lan_\w+) \{", self.rulesets[-1], re.M)
            )
            return CommandResult(0, "", "")
        if args[1:] == ["list", "tables"]:
            return CommandResult(
                0, "".join(f"table ip {name}\n" for name in sorted(self.tables)), ""
            )
        assert args[1:4] == ["delete", "table", "ip"], args
        self.changes.append(args)
        self.tables.discard(args[4])
        return CommandResult(0, "", "")

    def _iptables(self, args):
        assert args[1:3] == ["-w", "5"], args
        verb, chain, rest = args[3], args[4], args[5:]
        if verb == "-S":
            lines = [f"-P {chain} ACCEPT", *(f"-A {chain} {rule}" for rule in self.chains[chain])]
            return CommandResult(0, "\n".join(lines) + "\n", "")
        self.changes.append(args)
        if self.iptables_returncode:
            return CommandResult(self.iptables_returncode, "", "iptables boom")
        if verb == "-I":
            assert rest[0] == "1", "ours go first"
            self.chains[chain].insert(0, " ".join(rest[1:]))
        else:
            assert verb == "-D", args
            self.chains[chain].remove(" ".join(rest))
        return CommandResult(0, "", "")

    def _ip(self, args):
        if args[1:3] == ["-4", "-o"]:
            assert args[3:] == ["route", "show", "table", "local", "proto", str(LAN_ROUTE_PROTOCOL)]
            lines = [
                f"local {address} dev lo scope host"
                for address, p in self.routes.items()
                if p == str(LAN_ROUTE_PROTOCOL)
            ]
            return CommandResult(0, "\n".join(lines) + "\n" * bool(lines), "")
        self.changes.append(args)
        verb, address = args[2], args[4].removesuffix("/32")
        assert args[3] == "local", args
        assert args[5:7] == ["dev", "lo"], args
        assert args[7:] == ["table", "local", "proto", str(LAN_ROUTE_PROTOCOL)], args
        if verb == "replace":
            self.routes[address] = str(LAN_ROUTE_PROTOCOL)
        else:
            assert verb == "del", args
            del self.routes[address]
        return CommandResult(0, "", "")

    def state(self):
        return (
            sorted(self.tables),
            {chain: list(rules) for chain, rules in self.chains.items()},
            dict(self.routes),
        )


@pytest.fixture
def container():
    return FakeContainer()


@pytest.fixture
def lan_firewall(tmp_path, container):
    registry = Registry(tmp_path / "guests")
    registry.create(make_guest("lab1", GUEST_A))
    registry.create(make_guest("w10-q", GUEST_B))
    ports, sessions = PortLedger(tmp_path / "ports"), LanLedger(tmp_path / "lan")
    guard = GuestFirewall(
        policy=POLICY,
        ledger=ports,
        registry=registry,
        runner=container,
        rules_file=tmp_path / "rules.nft",
        lan_ledger=sessions,
    )
    return guard, container, sessions


def test_opening_a_session_loads_its_pairs_and_adds_the_iptables_rules_routes_and_tables(
    lan_firewall,
):
    guard, container, _ = lan_firewall

    guard.open_lan_session(SESSION_A)

    assert elements(container.rulesets[-1], "lan_tcp") >= {f"{GUEST_A} . {DC} . 445"}
    assert container.chains["OUTPUT"] == [OUTPUT_ACCEPT]
    assert container.chains["INPUT"] == [INPUT_ACCEPT]
    assert set(container.routes) == {DC, FILE_SERVER}
    assert container.tables == {"tartarus_lan_raw", "tartarus_lan_ttl"}


def test_the_iptables_rules_go_first_and_leave_the_rooters_and_foreign_rules_where_they_are(
    lan_firewall,
):
    guard, container, _ = lan_firewall
    container.chains["OUTPUT"] = [FOREIGN_RULE, ROOTER_RULE]
    container.chains["INPUT"] = [ROOTER_RULE, FOREIGN_RULE]

    guard.open_lan_session(SESSION_A)

    assert container.chains["OUTPUT"] == [OUTPUT_ACCEPT, FOREIGN_RULE, ROOTER_RULE]
    assert container.chains["INPUT"] == [INPUT_ACCEPT, ROOTER_RULE, FOREIGN_RULE]


def test_a_second_apply_runs_nothing_that_changes_anything(lan_firewall):
    guard, container, _ = lan_firewall
    guard.open_lan_session(SESSION_A)
    container.changes.clear()

    guard.apply()

    assert container.changes == []


def test_a_stale_rule_route_and_table_of_ours_are_removed_and_foreign_ones_stay(lan_firewall):
    guard, container, _ = lan_firewall
    stale_rule = OUTPUT_ACCEPT.replace(GUEST_A, "192.168.150.99")
    container.chains["OUTPUT"] = [stale_rule, FOREIGN_RULE, ROOTER_RULE]
    container.chains["INPUT"] = [INPUT_ACCEPT.replace(GUEST_A, "192.168.150.99"), ROOTER_RULE]
    container.routes = {"192.168.150.230": str(LAN_ROUTE_PROTOCOL), "192.168.150.231": "kernel"}
    container.tables = {"tartarus_lan_raw", "tartarus_lan_ttl"}

    guard.apply()

    assert container.chains == {"OUTPUT": [FOREIGN_RULE, ROOTER_RULE], "INPUT": [ROOTER_RULE]}
    assert container.routes == {"192.168.150.231": "kernel"}
    assert container.tables == set()


def test_a_rule_that_carries_our_comment_but_is_not_the_one_wanted_is_replaced(lan_firewall):
    guard, container, _ = lan_firewall
    wrong = OUTPUT_ACCEPT.replace("-j ACCEPT", "-j DROP")
    container.chains["OUTPUT"] = [wrong]

    guard.open_lan_session(SESSION_A)

    assert container.chains["OUTPUT"] == [OUTPUT_ACCEPT]


def test_two_sessions_of_one_guest_share_the_rules_and_closing_one_keeps_them(lan_firewall):
    guard, container, _ = lan_firewall
    guard.open_lan_session(SESSION_A)
    guard.open_lan_session(LanSession("task-3", GUEST_A, (LanTarget(PRINTER, (9100,)),)))

    assert container.chains["OUTPUT"] == [OUTPUT_ACCEPT]

    guard.close_lan_session("task-1")

    assert container.chains["OUTPUT"] == [OUTPUT_ACCEPT]
    assert set(container.routes) == {PRINTER}
    assert elements(container.rulesets[-1], "lan_tcp") == {f"{GUEST_A} . {PRINTER} . 9100"}


def test_two_guests_get_a_rule_each_and_a_route_for_every_target(lan_firewall):
    guard, container, _ = lan_firewall

    guard.open_lan_session(SESSION_A)
    guard.open_lan_session(SESSION_B)

    assert sorted(container.chains["OUTPUT"]) == sorted(
        [OUTPUT_ACCEPT, OUTPUT_ACCEPT.replace(GUEST_A, GUEST_B)]
    )
    assert set(container.routes) == {DC, FILE_SERVER, PRINTER}


def test_closing_the_last_session_removes_everything_that_was_added(lan_firewall):
    guard, container, _ = lan_firewall
    container.chains["OUTPUT"] = [FOREIGN_RULE, ROOTER_RULE]
    container.routes = {"192.168.150.231": "kernel"}
    guard.apply()
    before = container.state()
    guard.open_lan_session(SESSION_A)
    guard.open_lan_session(SESSION_B)

    guard.close_lan_session("task-1")
    guard.close_lan_session("task-2")

    assert container.state() == before


def test_closing_a_session_that_is_not_open_is_harmless(lan_firewall):
    guard, container, _ = lan_firewall

    guard.close_lan_session("never-opened")

    assert container.state() == ([], {"INPUT": [], "OUTPUT": []}, {})


def test_the_ruleset_after_the_last_session_closes_is_the_one_without_any_session(lan_firewall):
    guard, container, _ = lan_firewall
    guard._ledger.record("lab1", [LAB1])
    guard._ledger.record("w10-q", [W10])
    guard.apply()
    golden = container.rulesets[-1]
    assert golden == (FIXTURES / "guest_firewall_running.nft").read_text()
    guard.open_lan_session(SESSION_A)
    assert container.rulesets[-1] != golden

    guard.close_lan_session("task-1")

    assert container.rulesets[-1] == golden
    assert "tartarus_lan" not in golden


def test_a_session_is_recorded_before_the_ruleset_is_applied_so_a_hook_event_rebuilds_it(
    lan_firewall,
):
    guard, container, sessions = lan_firewall
    guard.open_lan_session(SESSION_A)
    container.chains = {"INPUT": [], "OUTPUT": []}
    container.routes = {}

    guard.hook("lab1", "started", STARTED_XML)

    assert sessions.sessions() == [SESSION_A]
    assert elements(container.rulesets[-1], "lan_tcp") >= {f"{GUEST_A} . {DC} . 445"}
    assert container.chains["OUTPUT"] == [OUTPUT_ACCEPT]
    assert set(container.routes) == {DC, FILE_SERVER}


def test_initialising_forgets_the_sessions_of_a_dead_container_and_cleans_what_they_left(
    lan_firewall,
):
    guard, container, sessions = lan_firewall
    guard.open_lan_session(SESSION_A)

    guard.initialise()

    assert sessions.sessions() == []
    assert container.state() == ([], {"INPUT": [], "OUTPUT": []}, {})
    assert "lan_tcp" not in container.rulesets[-1]


def test_a_session_that_is_not_valid_for_the_policy_applies_nothing(lan_firewall):
    guard, container, sessions = lan_firewall
    outside = LanSession("task-1", GUEST_A, (LanTarget("172.19.0.2", (8000,)),))

    with pytest.raises(ValueError, match="block"):
        guard.open_lan_session(outside)

    assert container.calls == []
    assert sessions.sessions() == []


def test_a_failure_while_opening_leaves_nothing_open_and_nothing_recorded(lan_firewall):
    guard, container, sessions = lan_firewall
    container.iptables_returncode = 1

    with pytest.raises(RuntimeError, match="iptables"):
        guard.open_lan_session(SESSION_A)

    assert sessions.sessions() == []
    container.iptables_returncode = 0
    guard.apply()
    assert container.state() == ([], {"INPUT": [], "OUTPUT": []}, {})
    assert "lan_tcp" not in container.rulesets[-1]


def test_nft_refusing_the_ruleset_stops_before_iptables_and_routes_are_touched(lan_firewall):
    guard, container, _ = lan_firewall
    container.returncode = 1

    with pytest.raises(RuntimeError, match="nft"):
        guard.open_lan_session(SESSION_A)

    assert container.changes == []


def test_without_a_lan_ledger_nothing_but_nft_runs_and_a_session_cannot_be_opened(tmp_path):
    container = FakeContainer()
    registry = Registry(tmp_path / "guests")
    guard = GuestFirewall(
        POLICY, PortLedger(tmp_path / "ports"), registry, container, tmp_path / "r.nft"
    )

    guard.apply()

    assert [call[:2] for call in container.calls] == [["nft", "-f"]]
    with pytest.raises(RuntimeError, match="session"):
        guard.open_lan_session(SESSION_A)


def test_a_command_that_is_not_installed_is_an_error_not_a_silent_open_door(lan_firewall):
    guard, container, _ = lan_firewall

    def missing(args, timeout=None, stdin=None):
        if args[0] == "iptables":
            raise MediaProblem(Fault.TOOL_MISSING, detail="iptables")
        return container(args, timeout)

    guard._runner = missing

    with pytest.raises(MediaProblem):
        guard.open_lan_session(SESSION_A)


def test_every_command_is_an_argument_list_with_only_validated_values(lan_firewall):
    guard, container, _ = lan_firewall

    guard.open_lan_session(SESSION_A)

    for call in container.calls:
        assert all(isinstance(part, str) for part in call)
        if call[0] == "iptables" and call[3] == "-I":
            assert shlex.split(" ".join(call)) == call


# --- the syntax, against the real nft where this machine has it -----------------------------------


def nft_check(ruleset: str) -> subprocess.CompletedProcess:
    # An unprivileged user namespace refuses `ip ttl set` in a route chain even for the prototype
    # that was measured to work; there the real check is the one in the cape image (step2-notes).
    return subprocess.run(  # noqa: S603 - fixed programs found on this machine
        [UNSHARE, "-rn", NFT, "-c", "-f", "/dev/stdin"],
        input=ruleset,
        capture_output=True,
        text=True,
        check=False,
    )


def nft_can_check() -> bool:
    return bool(NFT and UNSHARE) and nft_check(lan_ruleset(SESSION_A)).returncode == 0


@pytest.mark.skipif(
    not nft_can_check(), reason="needs nft that can check a route-hook chain in a user namespace"
)
@pytest.mark.parametrize("sessions", [(), (SESSION_A,), (SESSION_A, SESSION_B)])
def test_nft_accepts_the_ruleset_for_zero_one_and_two_sessions(sessions):
    checked = nft_check(lan_ruleset(*sessions))

    assert checked.returncode == 0, checked.stderr
