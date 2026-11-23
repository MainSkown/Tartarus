"""When many contacts with fake hosts become one derived event.

The Sigma matcher looks at one event at a time, so "one process swept the LAN" has to be an event
of its own. The three rules and their numbers are here, and only here: they are starting values
from the flood data of the fake LAN spike (docs/features/fake-lan-plan.md, S10), to be tuned on
real runs.
"""

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any


@dataclass(frozen=True)
class BurstRule:
    """A burst is `min_hosts` distinct hosts over at least `min_services` distinct known services,
    whose first and last sighting are at most `window` apart (the end of the window included).
    """

    action: str
    window: timedelta
    min_hosts: int
    min_services: int = 0


SWEEP = BurstRule("lan-sweep", window=timedelta(seconds=30), min_hosts=5)
FAN_OUT = BurstRule("lan-fan-out", window=timedelta(minutes=5), min_hosts=4, min_services=2)
CREDENTIAL_SPRAY = BurstRule("lan-credential-spray", window=timedelta(minutes=5), min_hosts=3)


@dataclass(frozen=True)
class Sighting:
    """One attempt of the guest on a fake host: a connect, or a login attempt (then with `user`)."""

    time: datetime
    host: str
    address: str
    service: str | None
    port: int | None
    process: Mapping[str, Any] | None
    event_id: str | None
    user: str | None = None


def bursts(sightings: Sequence[Sighting], rule: BurstRule) -> list[list[Sighting]]:
    """The windows of `sightings` (one process, one key) that meet `rule`.

    A window opens at the earliest sighting not yet used and takes everything within `rule.window`
    of it; when it does not meet the rule the next sighting opens one. A window that does meet it
    is a burst and uses all its sightings, so a long scan is one burst per window, not one per host.
    """
    ordered = sorted(sightings, key=lambda sighting: sighting.time)
    found: list[list[Sighting]] = []
    hosts: Counter[str] = Counter()
    services: Counter[str] = Counter()
    start = end = 0
    while start < len(ordered):
        while end < len(ordered) and ordered[end].time - ordered[start].time <= rule.window:
            _count(hosts, services, ordered[end], 1)
            end += 1
        if len(hosts) >= rule.min_hosts and len(services) >= rule.min_services:
            found.append(ordered[start:end])
            start = end
            hosts.clear()
            services.clear()
        else:
            _count(hosts, services, ordered[start], -1)
            start += 1
    return found


def _count(hosts: Counter[str], services: Counter[str], sighting: Sighting, step: int) -> None:
    for counter, name in ((hosts, sighting.host), (services, sighting.service)):
        if name is None:
            continue
        counter[name] += step
        if counter[name] == 0:
            del counter[name]
