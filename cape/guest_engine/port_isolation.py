"""Sets the isolated flag on a started guest's port of the shared bridge, and checks that it took.

The bridge forwards between its ports unless they are isolated, and the firewall's bridge table
only checks each guest's own source MAC and address, so this flag is all that stops one running
guest reaching another's agent, SMB or ping. It is set here, by the qemu hook, over netlink with
`bridge link set`, which needs only CAP_NET_ADMIN. libvirt's own `<port isolated='yes'/>` writes
sysfs, which is read-only in a container that is not privileged, so no domain carries that element.
"""

import json
from collections.abc import Sequence

from guest_engine.firewall import INTERFACE_NAME, GuestPort
from guest_engine.media import Runner
from guest_engine.media.errors import MediaProblem

BRIDGE_TIMEOUT_S = 10


def isolate_ports(ports: Sequence[GuestPort], runner: Runner) -> None:
    """Isolate every port, or raise `RuntimeError`/`ValueError` naming the first that cannot be."""
    for port in ports:
        _isolate(_checked_tap(port), runner)


def _checked_tap(port: GuestPort) -> str:
    if not INTERFACE_NAME.fullmatch(port.tap):
        raise ValueError(f"not a valid tap name: {port.tap!r}")
    return port.tap


def _run_bridge(command: Sequence[str], tap: str, runner: Runner) -> str:
    try:
        result = runner(command, BRIDGE_TIMEOUT_S)
    except MediaProblem as problem:
        raise RuntimeError(f"cannot isolate port {tap}: bridge: {problem}") from problem
    if result.returncode != 0:
        reason = result.stderr.strip() or f"exit status {result.returncode}"
        raise RuntimeError(f"cannot isolate port {tap}: {reason}")
    return result.stdout


def _isolate(tap: str, runner: Runner) -> None:
    _run_bridge(["bridge", "link", "set", "dev", tap, "isolated", "on"], tap, runner)
    # A set that did nothing, or on a tap that is not a bridge port, must not pass for isolation.
    shown = _run_bridge(["bridge", "-d", "-j", "link", "show", "dev", tap], tap, runner)
    if not _reads_isolated(shown):
        raise RuntimeError(f"port {tap} is not isolated after setting the flag")


def _reads_isolated(show_output: str) -> bool:
    try:
        links = json.loads(show_output)
    except ValueError:
        return False
    return bool(links) and all(link.get("isolated") is True for link in links)
