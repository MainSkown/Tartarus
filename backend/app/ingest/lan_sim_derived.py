"""The events derived from many contacts with fake hosts: `lan-sweep`, `lan-fan-out` and
`lan-credential-spray`. Rules and thresholds are in `app.ingest.lan_derived`.

Sweeps and fan-outs come from the report (CAPE's `tcp[]` flows and capemon's `connect` calls), not
from the daemon's log: the daemon only sees connections to open ports, so a scan of closed ports
exists only there. A spray is about logins, so it comes from the login events the daemon logged.
CAPE's `dead_hosts` is not read: it lists unanswered endpoints without a time, so it cannot take
part in a window, and the `connect` call of a monitored process covers the same attempt.
"""

from collections import defaultdict
from collections.abc import Callable, Hashable, Iterable, Iterator, Mapping
from datetime import datetime
from typing import Any

from app.ingest.cape_network import flow_time
from app.ingest.ecs import EventFactory, EventShape, SourceRecord, format_timestamp, truncate
from app.ingest.lan_derived import (
    CREDENTIAL_SPRAY,
    FAN_OUT,
    SWEEP,
    BurstRule,
    Sighting,
    bursts,
)
from app.ingest.lan_fields import lan_section
from app.ingest.protocol import IngestContext, LanHost
from app.ingest.reading import mapping_list, section, text_or_none, to_int

DATASET = "lan-sim.derived"
SOURCE_FILE = "derived"
SUMMARY_LIMIT = 300
MAX_RELATED_EVENTS = 50
MAX_RAW_SIGHTINGS = 100
CAPEMON_DATASET = "capemon.derived"
NETWORK_CONNECTION = "network-connection"
LOGIN_ATTEMPT = "lan-login-attempt"

type Event = Mapping[str, Any]


def _shape(rule: BurstRule, categories: tuple[str, ...], event_type: str) -> EventShape:
    return EventShape(rule.action, categories, (event_type,), "network", DATASET)


SHAPES = {
    SWEEP.action: _shape(SWEEP, ("network",), "connection"),
    FAN_OUT.action: _shape(FAN_OUT, ("network",), "connection"),
    CREDENTIAL_SPRAY.action: _shape(CREDENTIAL_SPRAY, ("network", "authentication"), "info"),
}


def derived_events(
    factory: EventFactory,
    report: Mapping[str, Any],
    context: IngestContext,
    capemon_events: Iterable[Event],
    login_events: Iterable[Event],
) -> Iterator[dict[str, Any]]:
    """The bursts of the run as events, oldest first, one per burst. `capemon_events` are what
    `CapemonNormalizer` derived from `report`; `login_events` are `lan-login-attempt` events (any
    other event in the stream is ignored).
    """
    contacts = _contacts(report, context, capemon_events)
    attempts = _login_attempts(login_events)
    found = [
        *((SWEEP, burst) for burst in _by_process(contacts, SWEEP, lambda s: s.port)),
        *((FAN_OUT, burst) for burst in _by_process(_with_service(contacts), FAN_OUT, _no_key)),
        *(
            (CREDENTIAL_SPRAY, burst)
            for burst in _by_process(
                attempts, CREDENTIAL_SPRAY, lambda s: (s.user or "").casefold()
            )
        ),
    ]
    found.sort(key=lambda found_burst: found_burst[1][0].time)
    for ordinal, (rule, burst) in enumerate(found):
        yield _event(factory, rule, burst, ordinal, context.lan_hosts)


def _no_key(_: Sighting) -> None:
    return None


def _with_service(sightings: Iterable[Sighting]) -> list[Sighting]:
    return [sighting for sighting in sightings if sighting.service is not None]


def _by_process(
    sightings: Iterable[Sighting], rule: BurstRule, key_of: Callable[[Sighting], Hashable]
) -> Iterator[list[Sighting]]:
    """The bursts of each (process, key): a sweep is one process on one port, never two processes'
    contacts added together. Sightings with no process are one group of their own.
    """
    groups: defaultdict[tuple[str | None, Hashable], list[Sighting]] = defaultdict(list)
    for sighting in sightings:
        entity = sighting.process["entity_id"] if sighting.process else None
        groups[entity, key_of(sighting)].append(sighting)
    for group in groups.values():
        yield from bursts(group, rule)


# --- the sightings -----------------------------------------------------------------------------


def _contacts(
    report: Mapping[str, Any], context: IngestContext, capemon_events: Iterable[Event]
) -> list[Sighting]:
    """Connects capemon saw, and the pcap's TCP flows to endpoints capemon did not see (the pcap's
    time is up to a few seconds early, and its flows name no process).
    """
    connects = [s for event in capemon_events if (s := _connect(event, context.lan_hosts))]
    covered = {(sighting.address, sighting.port) for sighting in connects}
    flows = (_flow(entry, context) for entry in mapping_list(section(report, "network").get("tcp")))
    return connects + [s for s in flows if s is not None and (s.address, s.port) not in covered]


def _connect(event: Event, lan_hosts: Mapping[str, LanHost]) -> Sighting | None:
    meta = event["event"]
    if meta["action"] != NETWORK_CONNECTION or meta["dataset"] != CAPEMON_DATASET:
        return None
    destination = event.get("destination", {})
    host = lan_hosts.get(destination.get("ip"))
    port = to_int(destination.get("port"))
    if host is None or port is None or "process" not in event:
        return None
    process = {name: value for name, value in event["process"].items() if name != "thread"}
    return Sighting(
        datetime.fromisoformat(event["@timestamp"]),
        host.fqdn,
        destination["ip"],
        host.services.get(port),
        port,
        process,
        meta["id"],
    )


def _flow(entry: Mapping[str, Any], context: IngestContext) -> Sighting | None:
    address = text_or_none(entry.get("dst"))
    port = to_int(entry.get("dport"))
    host = context.lan_hosts.get(address) if address else None
    if address is None or host is None or port is None:
        return None
    return Sighting(
        flow_time(entry, context), host.fqdn, address, host.services.get(port), port, None, None
    )


def _login_attempts(events: Iterable[Event]) -> list[Sighting]:
    attempts = []
    for event in events:
        user = event.get("user", {}).get("name")
        if event["event"]["action"] != LOGIN_ATTEMPT or not isinstance(user, str) or not user:
            continue
        lan = event["tartarus"]["lan"]
        destination = event["destination"]
        attempts.append(
            Sighting(
                datetime.fromisoformat(event["@timestamp"]),
                lan["host"],
                destination["ip"],
                lan.get("service"),
                destination.get("port"),
                event.get("process"),
                event["event"]["id"],
                user,
            )
        )
    return attempts


# --- the events --------------------------------------------------------------------------------


def _event(
    factory: EventFactory,
    rule: BurstRule,
    burst: list[Sighting],
    ordinal: int,
    lan_hosts: Mapping[str, LanHost],
) -> dict[str, Any]:
    first = burst[0]
    hosts = _distinct(s.host for s in burst)
    services = _distinct(s.service for s in burst if s.service)
    sections = {"related": _related(burst, hosts), **_rule_sections(rule, first)}
    if first.process:
        sections["process"] = dict(first.process)
    raw = {
        "rule": rule.action,
        "window_seconds": rule.window.total_seconds(),
        "sightings": [
            {"time": format_timestamp(s.time), "host": s.host, "port": s.port}
            for s in burst[:MAX_RAW_SIGHTINGS]
        ],
    }
    return factory.build(
        SHAPES[rule.action],
        SourceRecord(ordinal, first.time, raw, source_file=SOURCE_FILE),
        truncate(_summary(rule, burst, len(hosts), services), SUMMARY_LIMIT),
        tartarus=lan_section(None, **_lan_fields(first, hosts, services, lan_hosts)),
        **sections,
    )


def _lan_fields(
    first: Sighting, hosts: list[str], services: list[str], lan_hosts: Mapping[str, LanHost]
) -> dict[str, Any]:
    fields: dict[str, Any] = {"count": len(hosts)}
    if services:
        fields["service"] = services[0] if len(services) == 1 else services
    if (known := lan_hosts.get(first.address)) is not None:
        fields["preset"] = known.preset
    return fields


def _related(burst: list[Sighting], hosts: list[str]) -> dict[str, Any]:
    related: dict[str, Any] = {"hosts": hosts, "ip": _distinct(s.address for s in burst)}
    if events := _distinct(s.event_id for s in burst if s.event_id)[:MAX_RELATED_EVENTS]:
        related["events"] = events
    return related


def _rule_sections(rule: BurstRule, first: Sighting) -> dict[str, Any]:
    """What a rule's event says beyond its hosts: the port swept, or the user name tried."""
    if rule is CREDENTIAL_SPRAY:
        return {"user": {"name": first.user}}
    sections: dict[str, Any] = {"network": {"transport": "tcp"}}
    if rule is SWEEP:
        sections["destination"] = {"port": first.port}
    return sections


def _summary(rule: BurstRule, burst: list[Sighting], hosts: int, services: list[str]) -> str:
    first = burst[0]
    who = _who(first.process)
    seconds = round((burst[-1].time - first.time).total_seconds())
    if rule is SWEEP:
        return f"{who} contacted {hosts} fake hosts on port {first.port} within {seconds} s"
    if rule is FAN_OUT:
        return f"{who} contacted {hosts} fake hosts over {', '.join(services)} within {seconds} s"
    return f"{who} tried the user name {first.user} on {hosts} fake hosts within {seconds} s"


def _who(process: Mapping[str, Any] | None) -> str:
    if process is None:
        return "A process that could not be identified"
    return str(process.get("name") or f"pid {process['pid']}")


def _distinct[T](values: Iterable[T]) -> list[T]:
    return list(dict.fromkeys(values))
