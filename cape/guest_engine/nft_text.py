"""The text nft reads: sets, chains and the one check every value gets before it lands in them."""

import ipaddress
from collections.abc import Sequence


def checked_address(address: str) -> str:
    if not isinstance(address, str):
        raise ValueError(f"not an IPv4 address: {address!r}")
    try:
        return str(ipaddress.IPv4Address(address))
    except ValueError:
        raise ValueError(f"not an IPv4 address: {address!r}") from None


def nft_set(name: str, key_type: str, elements: Sequence[str], intervals: bool = False) -> str:
    lines = [f"    set {name} {{", f"        type {key_type}"]
    if intervals:
        lines.extend(["        flags interval", "        auto-merge"])
    if elements:
        lines.append(f"        elements = {{ {', '.join(elements)} }}")
    lines.append("    }")
    return "\n".join(lines)


def nft_chain(name: str, rules: Sequence[str], hook: str = "") -> str:
    lines = [f"    chain {name} {{"]
    if hook:
        lines.append(f"        {hook}")
    lines.extend(f"        {rule}" for rule in rules)
    lines.append("    }")
    return "\n".join(lines)
