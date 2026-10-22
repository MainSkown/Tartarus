"""What a guest on the `tt-guest` bridge may reach, and as whom.

CAPE's rooter opens a route for one guest address and inserts its FORWARD jumps again whenever it
or `cuckoo.py` starts, accept chain first; its rules match only that address. A guest that takes
another address, reaches the container's own listeners, or is routed back to the bridge by the
container escapes them. The rules here are an nftables table of their own at a priority before
iptables' chains, so the rooter's order and its cleanup (which only rewrites iptables) never touch
them:

- inet table, input: a guest reaches the gateway address and nothing else the container owns
  (CAPE's web and API, guacd and the control service listen on other addresses of the container);
- inet table, forward: a guest is never routed back onto the bridge, and never to a private,
  loopback, link-local or multicast address nor to a network the container is on, whatever route
  the rooter opened;
- bridge table: a frame from a port must carry that port's MAC, and an address that belongs to a
  running guest or to the gateway may only be used by the port that guest is on.
"""

import ipaddress
import json
import re
import xml.etree.ElementTree as ET
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path

from guest_engine.media import Runner
from guest_engine.profile import SLUG
from guest_engine.registry import Registry, write_atomically

TABLE = "tartarus_guest"
RESERVED_NETWORKS = (
    "0.0.0.0/8",
    "10.0.0.0/8",
    "100.64.0.0/10",
    "127.0.0.0/8",
    "169.254.0.0/16",
    "172.16.0.0/12",
    "192.168.0.0/16",
    "224.0.0.0/3",
)
STARTED_OPERATIONS = ("started",)
STOPPED_OPERATIONS = ("stopped", "release")
INTERFACE_NAME = re.compile(r"[A-Za-z0-9_.-]{1,15}")
MAC_ADDRESS = re.compile(r"[0-9a-f]{2}(:[0-9a-f]{2}){5}")
NFT_TIMEOUT_S = 30


@dataclass(frozen=True)
class FirewallPolicy:
    bridge: str
    gateway: str
    subnet: str
    networks: tuple[str, ...] = ()

    @property
    def unreachable(self) -> tuple[str, ...]:
        """What a guest must never reach: the reserved ranges and the networks found at start."""
        return tuple(dict.fromkeys((*RESERVED_NETWORKS, *self.networks)))


@dataclass(frozen=True)
class GuestPort:
    """The bridge port (tap device) of one running domain, with the MAC its guest is given."""

    domain: str
    tap: str
    mac: str


def _is_on_bridge(words: Sequence[str], bridge: str) -> bool:
    return "dev" in words and words[words.index("dev") + 1] == bridge


def _destination(words: Sequence[str]) -> str:
    if words[0] == "default" and "via" in words:
        return words[words.index("via") + 1] + "/32"
    return words[0]


def networks_behind(route_table: str, bridge: str) -> list[str]:
    """The networks and gateways in `ip -4 -o route` output, except the guest bridge's own."""
    found: list[str] = []
    for line in route_table.splitlines():
        words = line.split()
        if not words or _is_on_bridge(words, bridge):
            continue
        try:
            network = ipaddress.ip_network(_destination(words), strict=False)
        except ValueError:
            continue
        if isinstance(network, ipaddress.IPv4Network):
            found.append(str(network))
    return found


def ports_in(domain_xml: str, bridge: str) -> list[GuestPort]:
    """The interfaces of a started domain that sit on `bridge`, as libvirt reports them."""
    domain = ET.fromstring(domain_xml)  # noqa: S314 - libvirt's own output
    name = domain.findtext("name") or ""
    ports = []
    for interface in domain.iterfind("devices/interface"):
        source, target, mac = (
            interface.find("source"),
            interface.find("target"),
            interface.find("mac"),
        )
        if source is None or target is None or mac is None:
            continue
        if bridge not in (source.get("bridge"), source.get("network")):
            continue
        ports.append(GuestPort(name, target.get("dev", ""), mac.get("address", "").lower()))
    return ports


def _checked_port(port: GuestPort) -> GuestPort:
    if not INTERFACE_NAME.fullmatch(port.tap) or not MAC_ADDRESS.fullmatch(port.mac):
        raise ValueError(f"not a valid port: tap {port.tap!r}, mac {port.mac!r}")
    return port


def _checked_address(address: str) -> str:
    try:
        return str(ipaddress.IPv4Address(address))
    except ValueError:
        raise ValueError(f"not an IPv4 address: {address!r}") from None


def _set(name: str, key_type: str, elements: Sequence[str], intervals: bool = False) -> str:
    lines = [f"    set {name} {{", f"        type {key_type}"]
    if intervals:
        lines.extend(["        flags interval", "        auto-merge"])
    if elements:
        lines.append(f"        elements = {{ {', '.join(elements)} }}")
    lines.append("    }")
    return "\n".join(lines)


def _chain(name: str, rules: Sequence[str], hook: str = "") -> str:
    lines = [f"    chain {name} {{"]
    if hook:
        lines.append(f"        {hook}")
    lines.extend(f"        {rule}" for rule in rules)
    lines.append("    }")
    return "\n".join(lines)


def _inet_table(policy: FirewallPolicy) -> str:
    bridge, gateway = policy.bridge, policy.gateway
    guest_input = _chain(
        "input",
        [
            f'iifname != "{bridge}" return',
            f"ip daddr {gateway} accept",
            "ip daddr 255.255.255.255 udp dport 67 accept",
            "counter drop",
        ],
        "type filter hook input priority -10; policy accept;",
    )
    guest_forward = _chain(
        "forward",
        [
            f'iifname != "{bridge}" return',
            f'oifname "{bridge}" counter drop',
            "ip daddr @unreachable counter reject",
            "meta nfproto ipv6 counter drop",
        ],
        "type filter hook forward priority -10; policy accept;",
    )
    unreachable = _set("unreachable", "ipv4_addr", policy.unreachable, intervals=True)
    return "\n".join(
        [
            f"table inet {TABLE}",
            f"delete table inet {TABLE}",
            f"table inet {TABLE} {{",
            unreachable,
            guest_input,
            guest_forward,
            "}",
        ]
    )


def _bridge_table(
    policy: FirewallPolicy, ports: Sequence[GuestPort], addresses: Mapping[str, str]
) -> str:
    port_macs = [f'"{port.tap}" . {port.mac}' for port in ports]
    owned = [
        (port, _checked_address(addresses[port.domain]))
        for port in ports
        if port.domain in addresses
    ]
    bound = [f'"{port.tap}" . {port.mac} . {address}' for port, address in owned]
    protected = [_checked_address(policy.gateway), *(address for _, address in owned)]
    subnet = policy.subnet
    from_guest = _chain(
        "from_guest",
        ["iifname . ether saddr @port_macs jump checked"],
        "type filter hook prerouting priority -200; policy drop;",
    )
    checked = _chain(
        "checked", ["ether type arp jump arp_from_guest", "ether type ip jump ip_from_guest"]
    )
    arp_from_guest = _chain(
        "arp_from_guest",
        [
            "iifname . arp saddr ether != @port_macs counter drop",
            "arp saddr ip 0.0.0.0 accept",
            f"arp saddr ip != {subnet} counter drop",
            "arp saddr ip @protected iifname . ether saddr . arp saddr ip @bound accept",
            "arp saddr ip @protected counter drop",
            "accept",
        ],
    )
    ip_from_guest = _chain(
        "ip_from_guest",
        [
            "ip saddr 0.0.0.0 udp sport 68 udp dport 67 accept",
            "ip saddr 0.0.0.0 counter drop",
            f"ip saddr != {subnet} counter drop",
            "ip saddr @protected iifname . ether saddr . ip saddr @bound accept",
            "ip saddr @protected counter drop",
            "accept",
        ],
    )
    return "\n".join(
        [
            f"table bridge {TABLE}",
            f"delete table bridge {TABLE}",
            f"table bridge {TABLE} {{",
            _set("port_macs", "ifname . ether_addr", port_macs),
            _set("protected", "ipv4_addr", protected),
            _set("bound", "ifname . ether_addr . ipv4_addr", bound),
            from_guest,
            checked,
            arp_from_guest,
            ip_from_guest,
            "}",
        ]
    )


def render_ruleset(
    policy: FirewallPolicy, ports: Sequence[GuestPort], addresses: Mapping[str, str]
) -> str:
    """The whole ruleset for the running `ports`; `addresses` maps a domain to its address.

    Raises `ValueError` for a port, address or network that is not what its name says, because
    every value lands in nft's input verbatim.
    """
    checked = [_checked_port(port) for port in ports]
    for network in policy.unreachable:
        ipaddress.IPv4Network(network)
    return _inet_table(policy) + "\n" + _bridge_table(policy, checked, addresses) + "\n"


class PortLedger:
    """Which ports are live, one file per domain: the hook cannot ask libvirt while it runs."""

    def __init__(self, directory: Path) -> None:
        self._directory = directory

    def _file(self, domain: str) -> Path:
        if not SLUG.fullmatch(domain):
            raise ValueError(f"not a guest domain name: {domain!r}")
        return self._directory / f"{domain}.json"

    def record(self, domain: str, ports: Sequence[GuestPort]) -> None:
        write_atomically(self._file(domain), json.dumps([asdict(port) for port in ports]) + "\n")

    def forget(self, domain: str) -> None:
        self._file(domain).unlink(missing_ok=True)

    def clear(self) -> None:
        for file in self._directory.glob("*.json"):
            file.unlink()

    def ports(self) -> list[GuestPort]:
        """Every recorded port; a file that cannot be read is skipped and its port stays unbound."""
        found: list[GuestPort] = []
        for file in sorted(self._directory.glob("*.json")):
            try:
                found.extend(GuestPort(**entry) for entry in json.loads(file.read_text()))
            except (OSError, ValueError, TypeError):
                continue
        return found


def store_policy(directory: Path, policy: FirewallPolicy) -> None:
    write_atomically(directory / "policy.json", json.dumps(asdict(policy)) + "\n")


def load_policy(directory: Path) -> FirewallPolicy:
    data = json.loads((directory / "policy.json").read_text())
    return FirewallPolicy(**{**data, "networks": tuple(data["networks"])})


def policy_for(
    environ: Mapping[str, str], route_table: str, bridge: str, default_subnet: str
) -> FirewallPolicy:
    wanted = environ.get("GUEST_SUBNET") or default_subnet
    try:
        subnet = ipaddress.IPv4Network(wanted)
    except ValueError:
        raise ValueError(f"GUEST_SUBNET must be an IPv4 network, not {wanted!r}") from None
    gateway = environ.get("GUEST_GATEWAY_IP") or str(subnet.network_address + 1)
    return FirewallPolicy(
        bridge=bridge,
        gateway=gateway,
        subnet=str(subnet),
        networks=tuple(networks_behind(route_table, bridge)),
    )


class GuestFirewall:
    def __init__(
        self,
        policy: FirewallPolicy,
        ledger: PortLedger,
        registry: Registry,
        runner: Runner,
        rules_file: Path,
    ) -> None:
        self._policy = policy
        self._ledger = ledger
        self._registry = registry
        self._runner = runner
        self._rules_file = rules_file

    def _registered_addresses(self) -> dict[str, str]:
        return {guest.name: guest.ip for guest in self._registry.list()}

    def initialise(self) -> None:
        """Start from no bound port: no guest can be on the bridge when the container starts."""
        self._ledger.clear()
        self.apply()

    def hook(self, domain: str, operation: str, domain_xml: str) -> None:
        """Handle one libvirt qemu hook event: bind a started domain, unbind a stopped one."""
        if operation in STARTED_OPERATIONS:
            self._ledger.record(domain, ports_in(domain_xml, self._policy.bridge))
        elif operation in STOPPED_OPERATIONS:
            self._ledger.forget(domain)
        else:
            return
        self.apply()

    def apply(self) -> None:
        ruleset = render_ruleset(self._policy, self._ledger.ports(), self._registered_addresses())
        write_atomically(self._rules_file, ruleset, mode=0o600)
        result = self._runner(["nft", "-f", str(self._rules_file)], NFT_TIMEOUT_S)
        if result.returncode != 0:
            raise RuntimeError(f"nft refused the guest firewall: {result.stderr.strip()}")
