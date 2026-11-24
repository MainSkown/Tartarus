"""`summary.lan`: what the sample did on the fake local network, per fake host.

Built once, at the final ingest, from the events the ingest just built; the live phase has none.
Every string came from malware through the daemon's log, so each is cleaned and capped again here
whatever the normaliser already did to it.
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.analyses.lan_models import (
    LanCredential,
    LanHostSummary,
    LanPresetRef,
    LanServiceUse,
    LanSummary,
    LanTotals,
    LanWrittenFile,
)
from app.ingest.attribution import NETWORK_CONNECTION, without_repeated_capemon_rows
from app.ingest.cape_network import DATASET as CAPE_NETWORK_DATASET
from app.ingest.lan_sim import (
    AGGREGATE,
    FILE_WRITE,
    LOGIN_ATTEMPT,
    SERVICE_REQUEST,
    SHARE_ACCESS,
)
from app.ingest.lan_sim_log import SHA256, clean_text
from app.ingest.protocol import LanHost
from app.ingest.reading import dig, text_or_none, to_int
from app.ingest.sysmon_mapping import DATASET as SYSMON_DATASET

MAX_TEXT = 256
MAX_PATH = 1024
MAX_FILES_PER_HOST = 100
MAX_CREDENTIALS_PER_HOST = 100

# One for each way a sample reaches a service; a file write is not one, it follows an access.
EACH_IS_ONE_ATTEMPT = frozenset(
    shape.action for shape in (LOGIN_ATTEMPT, SHARE_ACCESS, SERVICE_REQUEST)
)


# The source that speaks for a connection when several saw it, best first; capemon's `connect`
# has no source port to pair with, so it is only kept when no other source has the endpoint.
CONNECTION_SOURCES = (CAPE_NETWORK_DATASET, SYSMON_DATASET)
LAST_BY_ACTION: dict[object, int] = {AGGREGATE.action: 1, NETWORK_CONNECTION: 2}


@dataclass
class _Use:
    attempts: int
    first: datetime
    last: datetime


@dataclass
class _Credential:
    count: int = 0
    success: bool = False
    secret: str | None = None


@dataclass
class _Host:
    entry: LanHost
    address: str
    first: datetime
    last: datetime
    services: dict[tuple[str | None, int | None], _Use] = field(default_factory=dict)
    daemon_ports: set[int] = field(default_factory=set)
    credentials: dict[tuple[str, str, str], _Credential] = field(default_factory=dict)
    files: list[LanWrittenFile] = field(default_factory=list)

    def touch(self, moment: datetime) -> None:
        self.first, self.last = min(self.first, moment), max(self.last, moment)

    def attempt(self, service: str | None, port: int | None, count: int, moment: datetime) -> None:
        use = self.services.setdefault((service, port), _Use(0, moment, moment))
        use.attempts += count
        use.first, use.last = min(use.first, moment), max(use.last, moment)


def lan_summary(
    events: Iterable[Mapping[str, Any]],
    lan_hosts: Mapping[str, LanHost],
    *,
    log_truncated: bool = False,
) -> LanSummary | None:
    """What the sample did on the fake LAN; None when the run had none (`lan_hosts` is empty).

    `events` are the final ingest's: the `network-connection` events flagged as simulated (the
    pcap's flows, Sysmon's EID 3 and capemon's `connect`, whichever the run has) and the
    `lan-sim` log events; anything else (the derived sweeps, which restate contacts already
    counted) is ignored. An attempt is one of: a login attempt, a share access, a service request
    (each a logged event), a connection to the host (so a scan that only connected counts), and,
    for a flood the daemon stopped logging, each event its `lan-aggregate` stands for. A file
    write is not an attempt. A host is listed when any such event touched it.

    A connection is counted once however many sources saw it. A pcap flow and a Sysmon event are
    the same connection when destination and source port agree, and the pcap speaks for it; a
    capemon connect (no source port) is dropped when another source has its destination, the
    same rule as the network view. A connection to a host and port the daemon logged events on
    is not counted either: those events are the attempts, and the connection is what carried them.
    """
    if not lan_hosts:
        return None
    hosts: dict[str, _Host] = {}
    for event, moment in _ordered(events, lan_hosts):
        host = hosts.get(address := dig(event, "destination", "ip"))
        if host is None:
            host = hosts[address] = _Host(lan_hosts[address], address, moment, moment)
        _record(host, event, moment)
    listed = sorted(hosts.values(), key=lambda host: (host.first, host.address))
    return _summary(lan_hosts, listed, log_truncated)


def _ordered(
    events: Iterable[Mapping[str, Any]], lan_hosts: Mapping[str, LanHost]
) -> list[tuple[Mapping[str, Any], datetime]]:
    """The events of the fake LAN with their time, oldest first. The aggregates come after the
    logged events, so a credential logged one by one is not overtaken by one a flood only named,
    and the connections last, so the ports the daemon logged on are known when they are counted.
    """
    contacts = [event for event in events if _is_lan_contact(event, lan_hosts)]
    timed = [(event, _time_of(event)) for event in _one_per_connection(contacts)]
    found = [(event, moment) for event, moment in timed if moment is not None]
    return sorted(found, key=lambda pair: (LAST_BY_ACTION.get(_action(pair[0]), 0), pair[1]))


def _one_per_connection(events: list[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    """`events` with each connection once: capemon's connect when another source has the
    endpoint is dropped, and of the rest the best source of each (destination, destination port,
    source port) stays. A connection with no source port is its own.
    """
    seen: set[tuple[object, ...]] = set()
    kept = []
    for event in sorted(without_repeated_capemon_rows(events), key=_source_rank):
        key = _connection_of(event)
        if key is not None:
            if key in seen:
                continue
            seen.add(key)
        kept.append(event)
    return kept


def _source_rank(event: Mapping[str, Any]) -> int:
    dataset = dig(event, "event", "dataset")
    return (
        CONNECTION_SOURCES.index(dataset)
        if dataset in CONNECTION_SOURCES
        else len(CONNECTION_SOURCES)
    )


def _connection_of(event: Mapping[str, Any]) -> tuple[object, ...] | None:
    source_port = dig(event, "source", "port")
    if _action(event) != NETWORK_CONNECTION or source_port is None:
        return None
    return (dig(event, "destination", "ip"), dig(event, "destination", "port"), source_port)


def _time_of(event: Mapping[str, Any]) -> datetime | None:
    stamp = dig(event, "@timestamp")
    try:
        return datetime.fromisoformat(stamp) if isinstance(stamp, str) else None
    except ValueError:
        return None


def _action(event: Mapping[str, Any]) -> object:
    return dig(event, "event", "action")


def _is_lan_contact(event: Mapping[str, Any], lan_hosts: Mapping[str, LanHost]) -> bool:
    if dig(event, "tartarus", "lan", "simulated") is not True:
        return False
    if dig(event, "destination", "ip") not in lan_hosts:
        return False
    return _action(event) in {
        NETWORK_CONNECTION,
        *EACH_IS_ONE_ATTEMPT,
        AGGREGATE.action,
        FILE_WRITE.action,
    }


def _record(host: _Host, event: Mapping[str, Any], moment: datetime) -> None:
    action = _action(event)
    port = to_int(dig(event, "destination", "port"))
    if action == NETWORK_CONNECTION and port in host.daemon_ports:
        return
    host.touch(moment)
    if action == FILE_WRITE.action:
        host.files.append(_written_file(event))
    elif action == AGGREGATE.action:
        _record_aggregate(host, event, moment)
    else:
        host.attempt(_service_of(host, event, port), port, 1, moment)
        if action != NETWORK_CONNECTION and port is not None:
            host.daemon_ports.add(port)
        if action == LOGIN_ATTEMPT.action:
            _record_login(host, event)


def _service_of(host: _Host, event: Mapping[str, Any], port: int | None) -> str | None:
    """The service the log names, else the one the preset serves on the port (a flow names none)."""
    if named := _text(dig(event, "tartarus", "lan", "service")):
        return named
    return None if port is None else host.entry.services.get(port)


def _record_login(host: _Host, event: Mapping[str, Any]) -> None:
    key = (
        _text(dig(event, "user", "name")),
        _text(dig(event, "user", "domain")),
        _text(dig(event, "tartarus", "lan", "mechanism")),
    )
    credential = host.credentials.setdefault(key, _Credential())
    credential.count += 1
    credential.success = credential.success or dig(event, "event", "outcome") == "success"
    if credential.secret is None:
        credential.secret = _secret(dig(event, "tartarus", "lan", "credential"))


def _record_aggregate(host: _Host, event: Mapping[str, Any], moment: datetime) -> None:
    service = _text(dig(event, "tartarus", "lan", "service")) or None
    port = next((port for port, kind in host.entry.services.items() if kind == service), None)
    count = to_int(dig(event, "tartarus", "lan", "count")) or 0
    host.attempt(service, port, count, moment)
    if port is not None:
        host.daemon_ports.add(port)
    users = _as_list(dig(event, "user", "name"))
    known = {user for user, _, _ in host.credentials}
    for user in (_text(name) for name in users):
        if user not in known:
            host.credentials[user, "", ""] = _Credential()
            known.add(user)
    if secrets := _as_list(dig(event, "tartarus", "lan", "credential")):
        unattributed = host.credentials.setdefault(("", "", ""), _Credential())
        unattributed.secret = unattributed.secret or _secret(secrets[0])


def _as_list(value: object) -> list[str]:
    items = value if isinstance(value, list) else [value]
    return [item for item in items if isinstance(item, str) and item]


def _written_file(event: Mapping[str, Any]) -> LanWrittenFile:
    sha256 = text_or_none(dig(event, "file", "hash", "sha256"))
    return LanWrittenFile(
        path=_text(dig(event, "file", "path"), MAX_PATH),
        share=_text(dig(event, "tartarus", "lan", "share")),
        size=to_int(dig(event, "file", "size")),
        sha256=sha256 if sha256 and SHA256.fullmatch(sha256) else None,
    )


def _text(value: object, limit: int = MAX_TEXT) -> str:
    return clean_text(value, limit) if isinstance(value, str) else ""


def _secret(value: object) -> str | None:
    return _text(value) or None


def _summary(
    lan_hosts: Mapping[str, LanHost], listed: list[_Host], log_truncated: bool
) -> LanSummary:
    any_host = next(iter(lan_hosts.values()))
    summaries = [_host_summary(host) for host in listed]
    return LanSummary(
        preset=LanPresetRef(
            id=_text(any_host.preset), name=_text(any_host.preset_name or any_host.preset)
        ),
        hosts=summaries,
        totals=LanTotals(
            hosts=len(summaries),
            attempts=sum(use.attempts for host in listed for use in host.services.values()),
            credentials=sum(len(host.credentials) for host in listed),
            files=sum(len(host.files) for host in listed),
        ),
        truncated=log_truncated,
    )


def _host_summary(host: _Host) -> LanHostSummary:
    credentials = [
        LanCredential(
            user=user,
            domain=domain,
            mechanism=mechanism,
            count=found.count,
            success=found.success,
            secret_as_sent=found.secret,
        )
        for (user, domain, mechanism), found in host.credentials.items()
    ]
    return LanHostSummary(
        fqdn=_text(host.entry.fqdn),
        address=host.address,
        role=_text(host.entry.role),
        services=[
            LanServiceUse(
                service=service, port=port, attempts=use.attempts, first=use.first, last=use.last
            )
            for (service, port), use in sorted(host.services.items(), key=_by_port)
        ],
        credentials=credentials[:MAX_CREDENTIALS_PER_HOST],
        credentials_more=max(len(credentials) - MAX_CREDENTIALS_PER_HOST, 0),
        files=host.files[:MAX_FILES_PER_HOST],
        files_more=max(len(host.files) - MAX_FILES_PER_HOST, 0),
        first=host.first,
        last=host.last,
    )


def _by_port(item: tuple[tuple[str | None, int | None], _Use]) -> tuple[bool, int, str]:
    (service, port), _ = item
    return (port is None, port or 0, service or "")
