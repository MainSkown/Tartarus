"""Turns the fake-LAN daemon's log (`lansim/events.jsonl`) into events, and derives the sweeps,
fan-outs and credential sprays that only show over many contacts.

What a record becomes and how a burst is found: docs/specs/data-model.md, "lan-sim". The flows to
the fake hosts are not repeated here: they are `cape-network`'s rows, flagged there, and these
events enrich them.
"""

from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field, replace
from typing import Any

from app.ingest.attribution import ProcessAttribution, endpoint_key
from app.ingest.capemon import CapemonNormalizer
from app.ingest.ecs import EventFactory, EventShape, SourceRecord, file_fields, truncate
from app.ingest.lan_fields import lan_section
from app.ingest.lan_sim_derived import derived_events
from app.ingest.lan_sim_log import LOG, LanLog, LogRecord, SessionEnd, read_lan_log
from app.ingest.protocol import IngestContext, LanHost

SOURCE = "lan-sim"
MODULE = "lan-sim"
DATASET = "lan-sim.log"
SOURCE_FILE = "events"
SUMMARY_LIMIT = 300
RENAME_ARROW = " -> "

# `event.type` of a share operation; anything the daemon's services add later is an `access`.
OPERATION_TYPES = {
    "create": "creation",
    "delete": "deletion",
    "rename": "change",
    "write": "change",
}


def _shape(action: str, categories: tuple[str, ...], event_type: str) -> EventShape:
    return EventShape(action, categories, (event_type,), "network", DATASET)


LOGIN_ATTEMPT = _shape("lan-login-attempt", ("network", "authentication"), "start")
SHARE_ACCESS = _shape("lan-share-access", ("network", "file"), "access")
FILE_WRITE = _shape("lan-file-write", ("network", "file"), "change")
SERVICE_REQUEST = _shape("lan-service-request", ("network",), "protocol")
AGGREGATE = _shape("lan-aggregate", ("network",), "info")


@dataclass(frozen=True)
class _Mapped:
    shape: EventShape
    summary: str
    lan: dict[str, Any] = field(default_factory=dict)
    sections: dict[str, Any] = field(default_factory=dict)


class LanSimNormalizer:
    """The fake hosts' log as events, and the bursts of contacts derived from the report.

    Without `context.lan_hosts` (the feature was off) it yields nothing. `session_end` is what the
    daemon's last record of the last `normalise` call said, for whoever reports a truncated log;
    it belongs to one ingest at a time.
    """

    source = SOURCE

    def __init__(self) -> None:
        self.session_end: SessionEnd | None = None

    def normalise(
        self, report: Mapping[str, Any], context: IngestContext
    ) -> Iterator[dict[str, Any]]:
        self.session_end = None
        if not context.lan_hosts:
            return
        log = _read(context)
        self.session_end = log.session_end
        capemon_events = list(CapemonNormalizer().normalise(report, context))
        attribution = ProcessAttribution(capemon_events)
        factory = EventFactory(context, source=SOURCE, source_file=SOURCE_FILE, module=MODULE)
        built = [_event(factory, record, context, attribution) for record in log.records]
        yield from built
        yield from derived_events(factory, report, context, capemon_events, built)


def _read(context: IngestContext) -> LanLog:
    if context.analysis_dir is None:
        return LanLog([], None)
    return read_lan_log(context.analysis_dir.joinpath(*LOG))


def _event(
    factory: EventFactory,
    record: LogRecord,
    context: IngestContext,
    attribution: ProcessAttribution,
) -> dict[str, Any]:
    mapped = _MAPPERS[record.type](record)
    address, known = _host_of(record, context.lan_hosts)
    sections = dict(mapped.sections)
    sections |= _endpoints(record, address)
    if record.service:
        sections["network"] = {"transport": "tcp", "protocol": record.service}
    lan = {"host": record.host, **({"service": record.service} if record.service else {})}
    related: dict[str, Any] = {}
    if record.destination is not None:
        found = attribution.lookup(endpoint_key(record.destination.ip, record.destination.port))
        if found is not None:
            sections["process"] = dict(found.process)
            related["events"] = [found.capemon_event_id]
    if related:
        sections["related"] = related
    return factory.build(
        mapped.shape,
        SourceRecord(record.index, record.fields.get("first_time") or record.time, record.raw),
        truncate(mapped.summary, SUMMARY_LIMIT),
        tartarus=lan_section(known, **lan, **mapped.lan),
        **sections,
    )


def _host_of(
    record: LogRecord, lan_hosts: Mapping[str, LanHost]
) -> tuple[str | None, LanHost | None]:
    """The fake host's address and preset entry: by the address the guest connected to, or for
    an aggregate (which has none) by the name the daemon logged.
    """
    if record.destination is not None:
        return record.destination.ip, lan_hosts.get(record.destination.ip)
    for address, host in lan_hosts.items():
        if host.fqdn == record.host:
            return address, host
    return None, None


def _endpoints(record: LogRecord, address: str | None) -> dict[str, Any]:
    sections: dict[str, Any] = {}
    if record.source is not None:
        sections["source"] = {"ip": record.source.ip, "port": record.source.port}
    destination: dict[str, Any] = {}
    if address is not None:
        destination["ip"] = address
    if record.destination is not None:
        destination["port"] = record.destination.port
    if record.host:
        destination["domain"] = record.host
    if destination:
        sections["destination"] = destination
    return sections


def _login_attempt(record: LogRecord) -> _Mapped:
    fields = record.fields
    user, domain = fields["user"], fields["domain"]
    success = fields["success"]
    verb = "logged in to" if success else "failed to log in to"
    summary = (
        f"{user or 'anonymous'} {verb} {record.host} ({record.service}) by {fields['mechanism']}"
    )
    lan = _present(mechanism=fields["mechanism"], credential=fields["secret"])
    return _Mapped(
        replace(LOGIN_ATTEMPT, outcome="success" if success else "failure"),
        summary,
        lan,
        {"user": _present(name=user, domain=domain)} if user or domain else {},
    )


def _share_access(record: LogRecord) -> _Mapped:
    fields = record.fields
    operation, share, path = fields["operation"], fields["share"], fields["path"]
    old_path, _, target = path.partition(RENAME_ARROW)
    sections = {"file": _file(old_path, target or None)} if old_path else {}
    shape = replace(SHARE_ACCESS, types=(OPERATION_TYPES.get(operation, "access"),))
    summary = f"{operation} {share}{path} on {record.host}"
    return _Mapped(shape, summary, _present(share=share, request=operation), sections)


def _file_write(record: LogRecord) -> _Mapped:
    fields = record.fields
    path, size = fields["path"], fields["size"]
    file = _file(path, None) if path else {}
    file["size"] = size
    if fields["sha256"]:
        file["hash"] = {"sha256": fields["sha256"]}
    cut = " (the stored copy is truncated)" if fields["truncated"] else ""
    summary = f"wrote {size} bytes to {fields['share']}{path} on {record.host}{cut}"
    return _Mapped(FILE_WRITE, summary, _present(share=fields["share"]), {"file": file})


def _service_request(record: LogRecord) -> _Mapped:
    name, detail = record.fields["name"], record.fields["detail"]
    summary = f"{name} on {record.host}" + (f": {detail}" if detail else "")
    return _Mapped(SERVICE_REQUEST, summary, _present(request=name, detail=detail))


def _aggregate(record: LogRecord) -> _Mapped:
    fields = record.fields
    by_type = ", ".join(f"{count} {kind}" for kind, count in fields["by_type"].items())
    summary = f"{fields['count']} events on {record.host} ({record.service}) kept as a count"
    summary += f": {by_type}" if by_type else ""
    sections = {"user": {"name": fields["users"]}} if fields["users"] else {}
    lan = {"count": fields["count"]}
    if fields["secrets"]:
        lan["credential"] = fields["secrets"]
    return _Mapped(AGGREGATE, summary, lan, sections)


_MAPPERS = {
    "login-attempt": _login_attempt,
    "share-access": _share_access,
    "file-write": _file_write,
    "service-request": _service_request,
    "aggregate": _aggregate,
}


def _file(path: str, target_path: str | None) -> dict[str, Any]:
    fields = file_fields(path, target_path)
    if not fields["name"]:
        del fields["name"]
    return fields


def _present(**fields: str) -> dict[str, str]:
    """The fields that have a value: an empty string means the client sent nothing."""
    return {name: value for name, value in fields.items() if value}
