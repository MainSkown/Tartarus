"""Keeps guests off each other: every guest NIC is an isolated port of the shared bridge.

`tt-guest` is a plain bridge, so without the flag two running guests reach each other's CAPE agent,
SMB and ping, while the gateway services (ResultServer, INetSim) stay reachable. Domains rendered
from `guest/domain/domain.xml.tpl` carry the flag; `isolate_guest` brings older ones up to date.
"""

import re

from guest_engine.host import Host

ISOLATED_PORT = "<port isolated='yes'/>"
INTERFACE = re.compile(r"<interface\b.*?</interface>", re.DOTALL)
PORT_ELEMENT = re.compile(r"<port\b[^>]*/>")
ISOLATED_YES = re.compile(r"""isolated=(['"])yes\1""")


def isolate_interfaces(xml: str) -> str:
    """`xml` with `<port isolated='yes'/>` in every `<interface>`; the rest is left byte for byte.

    Edited as text because ElementTree would rewrite the namespace prefixes of libvirt's output.
    """
    return INTERFACE.sub(lambda match: _isolated(match.group(0)), xml)


def _isolated(interface: str) -> str:
    existing = PORT_ELEMENT.search(interface)
    if existing is None:
        return interface.replace("</interface>", f"{ISOLATED_PORT}</interface>")
    if ISOLATED_YES.search(existing.group(0)):
        return interface
    return interface.replace(existing.group(0), ISOLATED_PORT)


def isolate_guest(host: Host, name: str) -> bool:
    """Isolate the persistent domain `name` and each of its snapshots; True when anything changed.

    A snapshot carries its own copy of the domain, and reverting to a memory snapshot starts the
    guest from that copy, so editing the domain alone would not survive the first revert.
    """
    changed = _isolate_domain(host, name)
    for snapshot in host.snapshot_names(name):
        changed |= _isolate_snapshot(host, name, snapshot)
    return changed


def _isolate_domain(host: Host, name: str) -> bool:
    current = host.domain_xml(name, inactive=True)
    if current is None:
        return False
    isolated = isolate_interfaces(current)
    if isolated == current:
        return False
    host.define(isolated)
    return True


def _isolate_snapshot(host: Host, name: str, snapshot: str) -> bool:
    current = host.snapshot_xml(name, snapshot)
    if current is None:
        return False
    isolated = isolate_interfaces(current)
    if isolated == current:
        return False
    host.redefine_snapshot(name, isolated, keep_current=host.current_snapshot(name) == snapshot)
    return True
