"""Opens or closes, for one guest address, the rooter rules CAPE sets for a task's route.

    python - enable|disable inetsim|internet|none GUEST_IP        (stdin: this file, in the cape container)

verify-isolation.sh needs a guest to be on each route without running an analysis. These are the
rooter commands `AnalysisManager.route_network` and `unroute_network` send at the pinned CAPE
commit (lib/cuckoo/core/analysis_manager.py), in the same order and with the same arguments, read
from the same configuration, so the iptables state is the one a real task produces.
"""

import sys

from lib.cuckoo.common.config import Config
from lib.cuckoo.core.rooter import rooter

GUEST_BRIDGE = "tt-guest"


def route_rules(action: str, route: str, guest_ip: str) -> None:
    routing = Config("routing")
    resultserver_port = str(Config("cuckoo").resultserver.port)

    if route == "inetsim":
        rooter(
            f"inetsim_{action}",
            guest_ip,
            str(routing.inetsim.server),
            str(routing.inetsim.dnsport),
            resultserver_port,
            str(routing.inetsim.ports),
        )
        egress = routing.inetsim.interface
    elif route == "none":
        rooter(f"drop_{action}", guest_ip, resultserver_port)
        return
    elif route == "internet":
        egress = routing.routing.internet
    else:
        raise SystemExit(f"unknown route {route!r}")

    rooter(f"libvirt_fwo_{action}", GUEST_BRIDGE, guest_ip)
    rooter(f"forward_{action}", GUEST_BRIDGE, egress, guest_ip)
    if route == "internet":
        rooter(f"forward_reject_{action}", GUEST_BRIDGE, egress, guest_ip, routing.routing.reject_segments)
        rooter(f"srcroute_{action}", routing.routing.rt_table, guest_ip)


if __name__ == "__main__":
    ACTIONS = ("enable", "disable")
    if len(sys.argv) != 4 or sys.argv[1] not in ACTIONS:  # noqa: PLR2004
        raise SystemExit(__doc__)
    route_rules(*sys.argv[1:])
