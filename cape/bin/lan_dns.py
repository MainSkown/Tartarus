"""The fake hosts' names as INetSim `dns_static` lines.

INetSim answers every name with the gateway, so a share path by name would reach INetSim and not
the fake host. A line it refuses stops every one of its services (a single label or an
underscore did, in the Step 0 spike), so a name is checked here again, whatever the loader
accepted, and any failure to load the presets leaves INetSim running without the lines: no DNS
for the fake hosts is a degraded analysis, no INetSim is a broken one.
"""

import ipaddress
from collections.abc import Callable, Iterable
from pathlib import Path

from guest_engine.lan_presets import Preset, dns_records, fqdn_problem, load_presets

Log = Callable[[str], None]


def dns_static_lines(presets: Iterable[Preset], log: Log) -> list[str]:
    lines = []
    for fqdn, address in dns_records(presets):
        if problem := _problem_with(fqdn, address):
            log(f"skipped the name {fqdn[:80]!r} for INetSim: {problem}")
            continue
        lines.append(f"dns_static {fqdn} {address}")
    return lines


def render(presets_dir: Path, subnet: str, log: Log) -> str:
    try:
        presets = load_presets(presets_dir, subnet)
    except (ValueError, OSError) as unloadable:
        log(f"{presets_dir} cannot be loaded, so INetSim starts with no dns_static: {unloadable}")
        return ""
    return "".join(f"{line}\n" for line in dns_static_lines(presets, log))


def _problem_with(fqdn: str, address: str) -> str | None:
    if problem := fqdn_problem(fqdn):
        return problem
    try:
        parsed = ipaddress.IPv4Address(address)
    except ValueError:
        return "the address is not a dotted IPv4 address"
    return None if str(parsed) == address else "the address is not in its canonical dotted form"
