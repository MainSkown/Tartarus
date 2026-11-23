"""What the guest firewall adds while a fake local network session is open.

A session lets one guest reach exactly the (host address, TCP port) pairs of its targets, and ping
those hosts, inside the fake address block (`lan_block`). It takes five pieces, because nft cannot
override what CAPE's rooter does in iptables:

- inet table, input chain: accept `guest . host . port` and `guest . host` echo pairs. The accept
  must sit in `tartarus_guest`'s own chain; one in another table still meets its final drop;
- bridge table: drop ARP and IP to the block unless the pair is allowed, and any frame that has a
  block address as its source. Never an `accept` for a pair, which would skip the spoofing checks
  below it;
- an nft table that does not track the allowed pairs: the rooter's `inetsim` route DNATs every
  packet of a guest, fake addresses included, and `none`/`drop` drop every reply to the guest;
- an nft table that sets the TTL of the fake hosts' replies to 128, what a guest's own system sends;
- iptables accepts for the block, inserted first with a comment of ours, and a local route for
  every target address, marked with a route protocol of ours. The rooter's own rules (comment
  `CAPE-rooter`) and every other rule and route are never touched.

Nothing here is rendered or added while no session exists. A session is applied whether or not
its guest is running: the firewall binds ports by running domain, so an address without a port is
simply unused.
"""

import ipaddress
import itertools
import json
import re
import shlex
from collections.abc import Collection, Iterable, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from guest_engine.lan_block import block_of
from guest_engine.media import CommandResult, Runner
from guest_engine.nft_text import checked_address, nft_chain, nft_set
from guest_engine.registry import write_atomically

SESSION_KEY = re.compile(r"[A-Za-z0-9][A-Za-z0-9-]{0,63}")
LOWEST_PORT, HIGHEST_PORT = 1, 65535

LAN_COMMENT = "tartarus-lan"
# Local routes of ours carry this protocol, so that listing by it finds only them (iproute2 reads
# 0-255; 77 is in no /etc/iproute2/rt_protos of the image and no routing daemon uses it).
LAN_ROUTE_PROTOCOL = 77
RAW_TABLE = "tartarus_lan_raw"
TTL_TABLE = "tartarus_lan_ttl"
LAN_TABLES = (RAW_TABLE, TTL_TABLE)
FAKE_HOST_TTL = 128
RAW_PRIORITY = -300
BEFORE_ROUTING_PRIORITY = -150
IPTABLES_WAIT = ["-w", "5"]
COMMAND_TIMEOUT_S = 30


def _checked_port(port: int) -> int:
    if type(port) is not int or not LOWEST_PORT <= port <= HIGHEST_PORT:
        raise ValueError(f"not a TCP port: {port!r}")
    return port


@dataclass(frozen=True)
class LanTarget:
    """One fake host: its address and the TCP ports a guest may reach (it may also ping it)."""

    address: str
    tcp_ports: tuple[int, ...]

    def __post_init__(self) -> None:
        self.validate()

    def validate(self) -> None:
        checked_address(self.address)
        for port in self.tcp_ports:
            _checked_port(port)


@dataclass(frozen=True)
class LanSession:
    key: str
    guest_address: str
    targets: tuple[LanTarget, ...]

    def __post_init__(self) -> None:
        self.validate()

    def validate(self) -> None:
        """Frozen does not stop `object.__setattr__`, so the firewall validates again at render."""
        if not isinstance(self.key, str) or not SESSION_KEY.fullmatch(self.key):
            raise ValueError(f"not a LAN session key: {self.key!r}")
        checked_address(self.guest_address)
        for target in self.targets:
            if not isinstance(target, LanTarget):
                raise ValueError("a LAN session lists LanTarget values only")
            target.validate()


def _numeric(address: str) -> int:
    return int(ipaddress.IPv4Address(address))


def check_fits(session: LanSession, subnet: str) -> None:
    """Refuse a session that would open anything but the block: a target elsewhere is a hole into
    the container's own services, a guest inside the block is a fake host."""
    first, last = block_of(subnet)
    guest = ipaddress.IPv4Address(checked_address(session.guest_address))
    if guest not in ipaddress.IPv4Network(subnet) or _numeric(first) <= int(guest) <= _numeric(
        last
    ):
        raise ValueError(
            f"guest address {session.guest_address} must be in {subnet}, outside the fake LAN block"
        )
    for target in session.targets:
        if not _numeric(first) <= _numeric(checked_address(target.address)) <= _numeric(last):
            raise ValueError(
                f"target address {target.address} is outside the fake LAN block {first}-{last}"
            )


class LanLedger:
    """The open sessions, one file per key: the libvirt hook rebuilds the ruleset from it."""

    def __init__(self, directory: Path) -> None:
        self._directory = directory

    def _file(self, key: str) -> Path:
        if not isinstance(key, str) or not SESSION_KEY.fullmatch(key):
            raise ValueError(f"not a LAN session key: {key!r}")
        return self._directory / f"{key}.json"

    def record(self, session: LanSession) -> None:
        write_atomically(self._file(session.key), json.dumps(asdict(session)) + "\n")

    def forget(self, key: str) -> None:
        self._file(key).unlink(missing_ok=True)

    def clear(self) -> None:
        for file in self._directory.glob("*.json"):
            file.unlink()

    def sessions(self) -> list[LanSession]:
        """Every recorded session; a file that cannot be read or is not a valid session is
        skipped, which leaves that session closed."""
        found: list[LanSession] = []
        for file in sorted(self._directory.glob("*.json")):
            try:
                session = session_from_dict(json.loads(file.read_text()))
            except (OSError, ValueError):
                continue
            if file.name == f"{session.key}.json":
                found.append(session)
        return found


def session_from_dict(data: Any) -> LanSession:
    """The inverse of `dataclasses.asdict(session)`; raises `ValueError` for anything else."""
    try:
        targets = tuple(
            LanTarget(target["address"], tuple(target["tcp_ports"])) for target in data["targets"]
        )
        return LanSession(data["key"], data["guest_address"], targets)
    except (TypeError, KeyError) as malformed:
        raise ValueError(f"not a LAN session: {type(malformed).__name__}") from malformed


def _pairs(sessions: Iterable[LanSession]) -> list[tuple[str, str]]:
    found = {
        (session.guest_address, target.address)
        for session in sessions
        for target in session.targets
    }
    return sorted(found, key=lambda pair: (_numeric(pair[0]), _numeric(pair[1])))


def _tcp_triples(sessions: Iterable[LanSession]) -> list[tuple[str, str, int]]:
    found = {
        (session.guest_address, target.address, port)
        for session in sessions
        for target in session.targets
        for port in target.tcp_ports
    }
    return sorted(found, key=lambda triple: (_numeric(triple[0]), _numeric(triple[1]), triple[2]))


def _hosts(sessions: Iterable[LanSession]) -> list[str]:
    return sorted({host for _, host in _pairs(sessions)}, key=_numeric)


def _guests(sessions: Iterable[LanSession]) -> list[str]:
    return sorted({session.guest_address for session in sessions}, key=_numeric)


@dataclass(frozen=True)
class LanFragments:
    """The nft text a session adds to `tartarus_guest`, and the tables of ours; all empty when no
    session is open, so the caller splices it in without a condition."""

    inet_sets: tuple[str, ...] = ()
    input_rules: tuple[str, ...] = ()
    bridge_sets: tuple[str, ...] = ()
    arp_rules: tuple[str, ...] = ()
    ip_rules: tuple[str, ...] = ()
    tables: str = ""


def _own_table(name: str, parts: Sequence[str]) -> str:
    return "\n".join(
        [f"table ip {name}", f"delete table ip {name}", f"table ip {name} {{", *parts, "}"]
    )


def _raw_table(bridge: str, pairs: Sequence[str]) -> str:
    chains = [
        nft_chain(
            "prerouting",
            [f'iifname "{bridge}" ip saddr . ip daddr @lan_pairs notrack'],
            f"type filter hook prerouting priority {RAW_PRIORITY}; policy accept;",
        ),
        nft_chain(
            "output",
            [f'oifname "{bridge}" ip daddr . ip saddr @lan_pairs notrack'],
            f"type filter hook output priority {RAW_PRIORITY}; policy accept;",
        ),
    ]
    return _own_table(RAW_TABLE, [nft_set("lan_pairs", "ipv4_addr . ipv4_addr", pairs), *chains])


def _ttl_table(bridge: str, hosts: Sequence[str]) -> str:
    chain = nft_chain(
        "output",
        [f'oifname "{bridge}" ip saddr @fake_hosts ip ttl set {FAKE_HOST_TTL}'],
        f"type route hook output priority {BEFORE_ROUTING_PRIORITY}; policy accept;",
    )
    return _own_table(TTL_TABLE, [nft_set("fake_hosts", "ipv4_addr", hosts), chain])


def fragments_for(sessions: Sequence[LanSession], bridge: str, subnet: str) -> LanFragments:
    """Raises `ValueError` for a session that is not valid for `subnet`, because every value
    lands in nft's input verbatim."""
    if not sessions:
        return LanFragments()
    for session in sessions:
        session.validate()
        check_fits(session, subnet)
    pairs = [f"{guest} . {host}" for guest, host in _pairs(sessions)]
    first, last = block_of(subnet)
    return LanFragments(
        inet_sets=(
            nft_set(
                "lan_tcp",
                "ipv4_addr . ipv4_addr . inet_service",
                [f"{guest} . {host} . {port}" for guest, host, port in _tcp_triples(sessions)],
            ),
            nft_set("lan_icmp", "ipv4_addr . ipv4_addr", pairs),
        ),
        input_rules=(
            "ip saddr . ip daddr . tcp dport @lan_tcp accept",
            "ip saddr . ip daddr @lan_icmp icmp type echo-request accept",
        ),
        bridge_sets=(
            nft_set("fake_block", "ipv4_addr", [f"{first}-{last}"], intervals=True),
            nft_set("lan_pairs", "ipv4_addr . ipv4_addr", pairs),
        ),
        arp_rules=(
            "arp saddr ip @fake_block counter drop",
            "arp daddr ip @fake_block arp saddr ip . arp daddr ip != @lan_pairs counter drop",
        ),
        ip_rules=(
            "ip saddr @fake_block counter drop",
            "ip daddr @fake_block ip saddr . ip daddr != @lan_pairs counter drop",
        ),
        tables="\n".join(
            [_raw_table(bridge, pairs), _ttl_table(bridge, _hosts(sessions))],
        ),
    )


# --- applying what nft cannot hold ----------------------------------------------------------------


def _succeeded(result: CommandResult, what: str) -> str:
    if result.returncode != 0:
        raise RuntimeError(f"{what} failed: {result.stderr.strip()}")
    return result.stdout


def _iptables_specs(guests: Iterable[str], subnet: str) -> dict[str, list[tuple[str, ...]]]:
    """The rules wanted, as `iptables -S` prints them after `-A <chain>`, so a listing compares
    equal to them."""
    first, last = block_of(subnet)
    comment = ("-m", "comment", "--comment", LAN_COMMENT, "-j", "ACCEPT")
    wanted: dict[str, list[tuple[str, ...]]] = {"OUTPUT": [], "INPUT": []}
    for guest in guests:
        wanted["OUTPUT"].append(
            ("-d", f"{guest}/32", "-m", "iprange", "--src-range", f"{first}-{last}", *comment)
        )
        wanted["INPUT"].append(
            ("-s", f"{guest}/32", "-m", "iprange", "--dst-range", f"{first}-{last}", *comment)
        )
    return wanted


def _our_iptables_rules(listing: str, chain: str) -> list[tuple[str, ...]]:
    found = []
    for line in listing.splitlines():
        words = shlex.split(line)
        ours = any(pair == ("--comment", LAN_COMMENT) for pair in itertools.pairwise(words))
        if words[:2] == ["-A", chain] and ours:
            found.append(tuple(words[2:]))
    return found


def _reconcile_iptables(runner: Runner, wanted: dict[str, list[tuple[str, ...]]]) -> None:
    def iptables(*arguments: str) -> str:
        result = runner(["iptables", *IPTABLES_WAIT, *arguments], COMMAND_TIMEOUT_S)
        return _succeeded(result, f"iptables {' '.join(arguments)}")

    for chain, specs in wanted.items():
        present = _our_iptables_rules(iptables("-S", chain), chain)
        kept: list[tuple[str, ...]] = []
        for spec in present:
            if spec in specs and spec not in kept:
                kept.append(spec)
            else:
                iptables("-D", chain, *spec)
        for spec in specs:
            if spec not in kept:
                iptables("-I", chain, "1", *spec)


def _local_route(verb: str, address: str) -> list[str]:
    return [
        "ip", "route", verb, "local", f"{address}/32", "dev", "lo",
        "table", "local", "proto", str(LAN_ROUTE_PROTOCOL),
    ]  # fmt: skip


def _reconcile_routes(runner: Runner, wanted: Collection[str]) -> None:
    listing = runner(
        ["ip", "-4", "-o", "route", "show", "table", "local", "proto", str(LAN_ROUTE_PROTOCOL)],
        COMMAND_TIMEOUT_S,
    )
    present = {
        line.split()[1].removesuffix("/32")
        for line in _succeeded(listing, "ip route show").splitlines()
        if line.startswith("local ")
    }
    for address in sorted(present - set(wanted), key=_numeric):
        _succeeded(
            runner(_local_route("del", address), COMMAND_TIMEOUT_S), f"ip route del {address}"
        )
    for address in sorted(set(wanted) - present, key=_numeric):
        _succeeded(
            runner(_local_route("replace", address), COMMAND_TIMEOUT_S), f"ip route add {address}"
        )


def _remove_stale_tables(runner: Runner) -> None:
    listing = _succeeded(runner(["nft", "list", "tables"], COMMAND_TIMEOUT_S), "nft list tables")
    for name in LAN_TABLES:
        if f"table ip {name}" in listing.splitlines():
            _succeeded(
                runner(["nft", "delete", "table", "ip", name], COMMAND_TIMEOUT_S),
                f"nft delete table {name}",
            )


def reconcile(runner: Runner, sessions: Sequence[LanSession], subnet: str) -> None:
    """Make the tables, iptables rules and local routes of ours match `sessions`; run after nft
    loaded the ruleset (which already replaced our tables when a session exists).

    Whatever is not ours stays: iptables rules without our comment, routes of another protocol.
    """
    if not sessions:
        _remove_stale_tables(runner)
    _reconcile_iptables(runner, _iptables_specs(_guests(sessions), subnet))
    _reconcile_routes(runner, _hosts(sessions))
