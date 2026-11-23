"""Where the fake local network lives in the guest subnet: one place for the address block.

Registered guests take offsets .10 to .99, the DHCP pool is .100 to .119, and
`scripts/verify-isolation.sh` invents .250, so the block sits between them. Presets, the firewall
and the daemon all read these numbers from here; the subnet is `GUEST_SUBNET`, never a literal.
"""

import ipaddress

FIRST_OFFSET = 200
LAST_OFFSET = 247
SUBNET_PREFIX_LENGTH = 24  # templates/tt-guest.xml hands out a 255.255.255.0 netmask


def offset_in_block(offset: int) -> bool:
    return FIRST_OFFSET <= offset <= LAST_OFFSET


def _checked_subnet(subnet: str) -> ipaddress.IPv4Network:
    network = ipaddress.IPv4Network(subnet)
    if network.prefixlen != SUBNET_PREFIX_LENGTH:
        raise ValueError(f"the guest subnet must be a /{SUBNET_PREFIX_LENGTH}, not {subnet}")
    return network


def address_at(subnet: str, offset: int) -> str:
    if not offset_in_block(offset):
        raise ValueError(
            f"offset {offset} is outside the fake LAN block {FIRST_OFFSET}-{LAST_OFFSET}"
        )
    return str(_checked_subnet(subnet).network_address + offset)


def block_of(subnet: str) -> tuple[str, str]:
    """The first and last address of the block in `subnet`."""
    return address_at(subnet, FIRST_OFFSET), address_at(subnet, LAST_OFFSET)
