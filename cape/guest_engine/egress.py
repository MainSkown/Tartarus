"""What the processes inside the cape container may connect to.

`guest_engine.firewall` constrains what a guest sends in; nothing there limits the container's own
programs, and the `cape` user parses hostile sample output. An nftables table of its own with an
output hook, default deny, keyed on the process user, applied before supervisord starts anything:

- loopback is open to everyone (CAPE's API, guacd's VNC, Docker's resolver at 127.0.0.11);
- replies on connections other containers or guests opened to this one are accepted;
- anything leaving through the guest bridge is accepted, whoever sends it;
- `cape` reaches the CAPE database and nothing else;
- root reaches https on public addresses only (the debug-symbol fetch from Microsoft's server);
- everything else is rejected at once, so a program that tries gets an error instead of a hang.

Guest traffic the rooter forwards is the forward hook, not output, and is not touched here.
"""

import ipaddress
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from guest_engine.firewall import (
    INTERFACE_NAME,
    NFT_TIMEOUT_S,
    RESERVED_NETWORKS,
    networks_behind,
    nft_chain,
    nft_set,
)
from guest_engine.media import Runner
from guest_engine.registry import write_atomically

TABLE = "tartarus_egress"
DATABASE_PORT = 5432
HTTPS_PORT = 443
ROOT_UID = 0
USER_NAME = re.compile(r"[a-z_][a-z0-9_-]{0,31}")


@dataclass(frozen=True)
class EgressPolicy:
    bridge: str
    cape_user: str
    database_network: str
    networks: tuple[str, ...] = ()

    @property
    def not_public(self) -> tuple[str, ...]:
        """What root must never reach over https: the reserved ranges and the networks found."""
        return tuple(dict.fromkeys((*RESERVED_NETWORKS, *self.networks)))


def _checked(policy: EgressPolicy) -> EgressPolicy:
    if not INTERFACE_NAME.fullmatch(policy.bridge):
        raise ValueError(f"not an interface name: {policy.bridge!r}")
    if not USER_NAME.fullmatch(policy.cape_user):
        raise ValueError(f"not a user name: {policy.cape_user!r}")
    for network in policy.not_public:
        ipaddress.IPv4Network(network)
    if not ipaddress.IPv4Network(policy.database_network).is_private:
        raise ValueError(f"the database network is not a private one: {policy.database_network!r}")
    return policy


def render_egress_ruleset(policy: EgressPolicy) -> str:
    """The whole egress table for `policy`.

    Raises `ValueError` for a name or network that is not what its name says, because every value
    lands in nft's input verbatim.
    """
    checked = _checked(policy)
    output = nft_chain(
        "output",
        [
            'oifname "lo" accept',
            "ct state established,related accept",
            f'oifname "{checked.bridge}" accept',
            f"meta skuid {checked.cape_user} ip daddr {checked.database_network} "
            f"tcp dport {DATABASE_PORT} accept",
            f"meta skuid {ROOT_UID} ip daddr != @not_public tcp dport {HTTPS_PORT} accept",
            "counter reject",
        ],
        "type filter hook output priority -10; policy drop;",
    )
    return (
        "\n".join(
            [
                f"table inet {TABLE}",
                f"delete table inet {TABLE}",
                f"table inet {TABLE} {{",
                nft_set("not_public", "ipv4_addr", checked.not_public, intervals=True),
                output,
                "}",
            ]
        )
        + "\n"
    )


def _connected_network(
    route_table: str, interface: str, address: ipaddress.IPv4Address
) -> ipaddress.IPv4Network | None:
    for line in route_table.splitlines():
        words = line.split()
        if not words or words[0] == "default" or words[1:2] != ["dev"] or words[2:3] != [interface]:
            continue
        try:
            network = ipaddress.IPv4Network(words[0], strict=False)
        except ValueError:
            continue
        if address in network:
            return network
    return None


def policy_for(
    environ: Mapping[str, str], route_table: str, bridge: str, cape_user: str
) -> EgressPolicy:
    """The policy for this container: the entrypoint says which address and interface are the
    CAPE database network's, the routes say how large that network is."""
    wanted, interface = environ.get("CAPE_DB_IP", ""), environ.get("CAPE_DB_IFACE", "")
    try:
        address = ipaddress.IPv4Address(wanted)
    except ValueError:
        raise ValueError(f"CAPE_DB_IP must be an IPv4 address, not {wanted!r}") from None
    network = _connected_network(route_table, interface, address)
    if network is None:
        raise ValueError(
            f"no database network found: {interface!r} has no route containing {address}"
        )
    return EgressPolicy(
        bridge=bridge,
        cape_user=cape_user,
        database_network=str(network),
        networks=tuple(networks_behind(route_table, bridge)),
    )


def apply_egress(policy: EgressPolicy, runner: Runner, rules_file: Path) -> None:
    write_atomically(rules_file, render_egress_ruleset(policy), mode=0o600)
    result = runner(["nft", "-f", str(rules_file)], NFT_TIMEOUT_S)
    if result.returncode != 0:
        raise RuntimeError(f"nft refused the egress firewall: {result.stderr.strip()}")
