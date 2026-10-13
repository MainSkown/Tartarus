import ipaddress
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from app.ingest.attribution import Key, ProcessAttribution, dns_key, endpoint_key, url_key
from app.ingest.capemon import CapemonNormalizer
from app.ingest.clock import epoch_to_datetime
from app.ingest.ecs import EventFactory, EventShape, SourceRecord
from app.ingest.protocol import IngestContext
from app.ingest.reading import mapping_list, section, text_or_none, to_int

SOURCE = "cape-network"
MODULE = "cape"
DATASET = "cape.network"
DEFAULT_SOURCE_FILE = "network"


def _shape(action: str, event_type: str) -> EventShape:
    return EventShape(action, ("network",), (event_type,), "network", DATASET)


DNS_QUERY = _shape("dns-query", "protocol")
FLOW = _shape("network-connection", "connection")
HTTP_REQUEST = _shape("http-request", "protocol")


@dataclass(frozen=True)
class _Candidate:
    shape: EventShape
    record: SourceRecord
    summary: str
    sections: dict[str, Any]
    attribution_key: Key | None = None
    related: dict[str, Any] = field(default_factory=dict)


class CapeNetworkNormalizer:
    """Turns `network.dns`, `tcp`, `udp` and `http` into network events.

    Time and attribution rules: docs/specs/data-model.md, "CAPE report normalisers (as built)".
    """

    source = SOURCE

    def normalise(
        self, report: Mapping[str, Any], context: IngestContext
    ) -> Iterator[dict[str, Any]]:
        candidates = sorted(
            _candidates(section(report, "network"), context), key=lambda c: c.record.timestamp
        )
        attribution = ProcessAttribution(CapemonNormalizer().normalise(report, context))
        factory = EventFactory(
            context, source=SOURCE, source_file=DEFAULT_SOURCE_FILE, module=MODULE
        )
        for candidate in candidates:
            yield _build(factory, candidate, attribution)


def _build(
    factory: EventFactory, candidate: _Candidate, attribution: ProcessAttribution
) -> dict[str, Any]:
    sections = dict(candidate.sections)
    related = dict(candidate.related)
    found = attribution.lookup(candidate.attribution_key) if candidate.attribution_key else None
    if found is not None:
        sections["process"] = dict(found.process)
        related["events"] = [found.capemon_event_id]
    if related:
        sections["related"] = related
    return factory.build(candidate.shape, candidate.record, candidate.summary, **sections)


def _candidates(network: Mapping[str, Any], context: IngestContext) -> Iterator[_Candidate]:
    dns_times: dict[str, datetime] = {}
    for index, entry in enumerate(mapping_list(network.get("dns"))):
        candidate = _dns_candidate(entry, index, context)
        if candidate is not None:
            dns_times.setdefault(_host_key(entry["request"]), candidate.record.timestamp)
            yield candidate
    for transport in ("tcp", "udp"):
        for index, entry in enumerate(mapping_list(network.get(transport))):
            if (flow := _flow_candidate(entry, transport, index, context)) is not None:
                yield flow
    for index, entry in enumerate(mapping_list(network.get("http"))):
        if (request := _http_candidate(entry, index, context, dns_times)) is not None:
            yield request


def _host_key(name: str) -> str:
    return name.casefold().rstrip(".")


def _dns_candidate(
    entry: Mapping[str, Any], index: int, context: IngestContext
) -> _Candidate | None:
    name = text_or_none(entry.get("request"))
    if name is None:
        return None
    timestamp = epoch_to_datetime(entry.get("first_seen")) or context.started_at
    record = SourceRecord(index, timestamp, entry, source_file="dns")
    question = {"name": name}
    if record_type := text_or_none(entry.get("type")):
        question["type"] = record_type
    dns: dict[str, Any] = {"question": question}
    answers = _answers(entry.get("answers"))
    related: dict[str, Any] = {}
    if answers:
        dns["answers"] = {"data": answers}
        if addresses := [answer for answer in answers if _is_ip(answer)]:
            related["ip"] = addresses
    summary = f"DNS query for {name}" + (f" answered {', '.join(answers)}" if answers else "")
    return _Candidate(
        DNS_QUERY,
        record,
        summary,
        {"dns": dns, "network": {"protocol": "dns"}},
        dns_key(name),
        related,
    )


def _answers(value: object) -> list[str]:
    return [data for answer in mapping_list(value) if (data := text_or_none(answer.get("data")))]


def _is_ip(text: str) -> bool:
    try:
        ipaddress.ip_address(text)
    except ValueError:
        return False
    return True


def _flow_candidate(
    entry: Mapping[str, Any], transport: str, index: int, context: IngestContext
) -> _Candidate | None:
    destination_ip = text_or_none(entry.get("dst"))
    if destination_ip is None:
        return None
    destination_port = to_int(entry.get("dport"))
    elapsed = entry.get("time")
    timestamp = context.started_at + _seconds(elapsed)
    record = SourceRecord(index, timestamp, entry, source_file=transport)
    source = _endpoint(entry.get("src"), to_int(entry.get("sport")))
    destination = _endpoint(destination_ip, destination_port)
    summary = f"{transport} flow {_label(source)} to {_label(destination)}"
    sections: dict[str, Any] = {"destination": destination, "network": {"transport": transport}}
    if source:
        sections["source"] = source
    return _Candidate(
        FLOW, record, summary, sections, endpoint_key(destination_ip, destination_port)
    )


def _seconds(value: object) -> timedelta:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return timedelta(0)
    try:
        return timedelta(seconds=value)
    except (OverflowError, ValueError):
        return timedelta(0)


def _endpoint(address: object, port: int | None) -> dict[str, Any]:
    fields: dict[str, Any] = {}
    if isinstance(address, str) and address:
        fields["ip"] = address
    if port is not None:
        fields["port"] = port
    return fields


def _label(endpoint: Mapping[str, Any]) -> str:
    address = endpoint.get("ip", "?")
    return f"{address}:{endpoint['port']}" if "port" in endpoint else str(address)


def _http_candidate(
    entry: Mapping[str, Any],
    index: int,
    context: IngestContext,
    dns_times: Mapping[str, datetime],
) -> _Candidate | None:
    host = text_or_none(entry.get("host"))
    url = text_or_none(entry.get("uri"))
    if host is None and url is None:
        return None
    timestamp = (
        epoch_to_datetime(entry.get("first_seen"))
        or (host and dns_times.get(_host_key(host)))
        or context.started_at
    )
    record = SourceRecord(index, timestamp, entry, source_file="http")
    destination: dict[str, Any] = {"domain": host} if host else {}
    if (port := to_int(entry.get("port"))) is not None:
        destination["port"] = port
    sections: dict[str, Any] = {"network": {"transport": "tcp", "protocol": "http"}}
    optional = {
        "destination": destination,
        "url": {"full": url} if url else {},
        "http": _method(entry.get("method")),
        "user_agent": _user_agent(entry.get("user-agent")),
    }
    sections |= {name: value for name, value in optional.items() if value}
    method = text_or_none(entry.get("method")) or "HTTP request"
    return _Candidate(
        HTTP_REQUEST, record, f"{method} {url or host}", sections, url_key(url) if url else None
    )


def _method(value: object) -> dict[str, Any]:
    method = text_or_none(value)
    return {"request": {"method": method}} if method else {}


def _user_agent(value: object) -> dict[str, Any]:
    agent = text_or_none(value)
    return {"original": agent} if agent else {}
