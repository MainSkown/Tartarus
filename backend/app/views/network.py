from collections import Counter
from collections.abc import Callable, Iterable, Sequence

from app.ingest.attribution import Key, dns_key, endpoint_key, url_key
from app.schemas.views_events import (
    DnsRow,
    FlowRow,
    HostRow,
    HttpRow,
    Listing,
    NetworkAlertRow,
    NetworkView,
    TlsRow,
)
from app.search.index import EventIndex
from app.views.event_fields import (
    TIME_ORDER,
    WITHOUT_RAW,
    Source,
    event_id,
    event_time,
    hits_of,
    int_at,
    process_ref,
    text_at,
    texts_at,
)

NETWORK_EVENT_CAP = 10_000
DEFAULT_LIST_LIMIT = 500
MAX_LIST_LIMIT = 2000
CALL_DERIVED_MODULE = "capemon"


def _key_of(event: Source) -> Key | None:
    action = text_at(event, "event", "action")
    if action == "dns-query" and (name := text_at(event, "dns", "question", "name")):
        return dns_key(name)
    if action == "network-connection" and (address := text_at(event, "destination", "ip")):
        return endpoint_key(address, int_at(event, "destination", "port"))
    if action == "http-request" and (url := text_at(event, "url", "full")):
        return url_key(url)
    return None


def _without_repeated_capemon_rows(events: Sequence[Source]) -> list[Source]:
    """A call capemon saw and the pcap also holds is one row, the pcap's, which names the
    process. A call only capemon saw (a blocked route leaves no traffic) stays.
    """
    in_pcap = {
        key
        for event in events
        if text_at(event, "event", "module") != CALL_DERIVED_MODULE and (key := _key_of(event))
    }
    return [
        event
        for event in events
        if text_at(event, "event", "module") != CALL_DERIVED_MODULE or _key_of(event) not in in_pcap
    ]


def _dns_row(event: Source) -> DnsRow | None:
    query = text_at(event, "dns", "question", "name")
    if query is None:
        return None
    return DnsRow(
        event_id=event_id(event),
        time=event_time(event),
        query=query,
        type=text_at(event, "dns", "question", "type"),
        answers=texts_at(event, "dns", "answers", "data"),
        process=process_ref(event),
    )


def _http_row(event: Source) -> HttpRow | None:
    url = text_at(event, "url", "full")
    if url is None:
        return None
    return HttpRow(
        event_id=event_id(event),
        time=event_time(event),
        method=text_at(event, "http", "request", "method"),
        url=url,
        host=text_at(event, "destination", "domain"),
        status=int_at(event, "http", "response", "status_code"),
        user_agent=text_at(event, "user_agent", "original"),
        process=process_ref(event),
    )


def _flow_row(event: Source) -> FlowRow:
    return FlowRow(
        event_id=event_id(event),
        time=event_time(event),
        transport=text_at(event, "network", "transport"),
        source_ip=text_at(event, "source", "ip"),
        source_port=int_at(event, "source", "port"),
        destination_ip=text_at(event, "destination", "ip"),
        destination_port=int_at(event, "destination", "port"),
        process=process_ref(event),
    )


def _hosts(
    dns: Iterable[DnsRow], http: Iterable[HttpRow], flows: Iterable[FlowRow]
) -> list[HostRow]:
    """Addresses count their connections; names count their lookups and requests."""
    dns = list(dns)
    addresses = Counter(flow.destination_ip for flow in flows if flow.destination_ip)
    names: Counter[str] = Counter(_name(row.query) for row in dns)
    names.update(_name(row.host) for row in http if row.host)
    names_of: dict[str, list[str]] = {}
    addresses_of: dict[str, list[str]] = {}
    for row in dns:
        for answer in row.answers:
            names_of.setdefault(answer, []).append(_name(row.query))
            addresses_of.setdefault(_name(row.query), []).append(answer)
    hosts = [
        HostRow(host=address, kind="ip", count=count, related=_distinct(names_of.get(address, [])))
        for address, count in addresses.items()
    ] + [
        HostRow(
            host=name, kind="domain", count=count, related=_distinct(addresses_of.get(name, []))
        )
        for name, count in names.items()
    ]
    return sorted(hosts, key=lambda host: (-host.count, host.host))


def _name(name: str) -> str:
    return name.casefold().rstrip(".")


def _distinct(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))


def _listing[T](rows: list[T], limit: int) -> Listing[T]:
    return Listing[T](items=rows[:limit], total=len(rows))


def shape_network(events: Sequence[Source], *, simulated: bool, limit: int) -> NetworkView:
    """Rows in the order given (time), each list cut to `limit` with its full total."""
    shown = _without_repeated_capemon_rows(events)
    dns = _rows(shown, "dns-query", _dns_row)
    http = _rows(shown, "http-request", _http_row)
    flows = _rows(shown, "network-connection", _flow_row)
    return NetworkView(
        dns=_listing(dns, limit),
        http=_listing(http, limit),
        tls=_listing(list[TlsRow](), limit),
        flows=_listing(flows, limit),
        alerts=_listing(list[NetworkAlertRow](), limit),
        hosts=_listing(_hosts(dns, http, flows), limit),
        simulated=simulated,
    )


def _rows[R](events: Iterable[Source], action: str, build: Callable[[Source], R | None]) -> list[R]:
    rows = (build(event) for event in events if text_at(event, "event", "action") == action)
    return [row for row in rows if row is not None]


async def network_view(
    index: EventIndex, analysis_id: int, *, simulated: bool, limit: int
) -> NetworkView:
    response = await index.search(
        analysis_id,
        {
            "size": NETWORK_EVENT_CAP,
            "query": {
                "bool": {
                    "filter": [
                        {"term": {"tartarus.lane": "network"}},
                        {"term": {"event.kind": "event"}},
                    ]
                }
            },
            "sort": TIME_ORDER,
            "_source": WITHOUT_RAW,
        },
    )
    return shape_network(hits_of(response), simulated=simulated, limit=limit)
