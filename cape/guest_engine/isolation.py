"""Takes libvirt's own port isolation out of guests that were defined with it.

The single source of truth for the isolated flag on a guest's bridge port is the qemu hook
(`port_isolation.py`): libvirt implements `<port isolated='yes'/>` by writing
/sys/class/net/<bridge>/brif/<tap>/isolated, and sysfs is read-only in a container that is not
privileged, so a domain carrying the element would not start there. Domains rendered from
`guest/domain/domain.xml.tpl` do not have it; `strip_guest` updates guests defined earlier.
"""

import re

from guest_engine.host import Host

INTERFACE = re.compile(r"<interface\b.*?</interface>", re.DOTALL)
PORT_ISOLATION = re.compile(r"\s*<port\b[^>]*\bisolated=[^>]*/>")


def strip_port_isolation(xml: str) -> str:
    """`xml` without the `<port isolated=.../>` of any `<interface>`; the rest is left as it was.

    Edited as text because ElementTree would rewrite the namespace prefixes of libvirt's output.
    """
    return INTERFACE.sub(lambda match: PORT_ISOLATION.sub("", match.group(0)), xml)


def strip_guest(host: Host, name: str) -> bool:
    """Strip the persistent domain `name` and each of its snapshots; True when anything changed.

    A snapshot carries its own copy of the domain, and reverting to a memory snapshot starts the
    guest from that copy, so editing the domain alone would not survive the first revert.
    """
    changed = _strip_domain(host, name)
    for snapshot in host.snapshot_names(name):
        changed |= _strip_snapshot(host, name, snapshot)
    return changed


def _strip_domain(host: Host, name: str) -> bool:
    current = host.domain_xml(name, inactive=True)
    if current is None:
        return False
    stripped = strip_port_isolation(current)
    if stripped == current:
        return False
    host.define(stripped)
    return True


def _strip_snapshot(host: Host, name: str, snapshot: str) -> bool:
    current = host.snapshot_xml(name, snapshot)
    if current is None:
        return False
    stripped = strip_port_isolation(current)
    if stripped == current:
        return False
    host.redefine_snapshot(name, stripped, keep_current=host.current_snapshot(name) == snapshot)
    return True
