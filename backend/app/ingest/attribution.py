"""Which process did a network record come from, when the capemon events say so exactly."""

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from app.ingest.reading import dig, to_int

DNS_QUERY = "dns-query"
NETWORK_CONNECTION = "network-connection"
HTTP_REQUEST = "http-request"
CAPEMON_MODULE = "capemon"

Key = tuple[str, ...]


@dataclass(frozen=True)
class Attribution:
    process: Mapping[str, Any]
    capemon_event_id: str


def dns_key(name: str) -> Key:
    return (DNS_QUERY, name.casefold().rstrip("."))


def endpoint_key(address: str, port: int | None) -> Key:
    return (NETWORK_CONNECTION, address, str(port))


def url_key(url: str) -> Key:
    return (HTTP_REQUEST, url)


def key_of(event: Mapping[str, Any]) -> Key | None:
    """What a network event is about, by the key a capemon event and a pcap row would share."""
    action = dig(event, "event", "action")
    if action == DNS_QUERY and isinstance(name := dig(event, "dns", "question", "name"), str):
        return dns_key(name) if name else None
    if action == NETWORK_CONNECTION and isinstance(address := dig(event, "destination", "ip"), str):
        return endpoint_key(address, to_int(dig(event, "destination", "port")))
    if action == HTTP_REQUEST and isinstance(url := dig(event, "url", "full"), str):
        return url_key(url) if url else None
    return None


def without_repeated_capemon_rows[E: Mapping[str, Any]](events: Sequence[E]) -> list[E]:
    """A call capemon saw and another source (the pcap, Sysmon) also holds is one row, the
    other's, which names the process. A call only capemon saw (a blocked route leaves no traffic)
    stays.
    """
    elsewhere = {
        key
        for event in events
        if dig(event, "event", "module") != CAPEMON_MODULE and (key := key_of(event))
    }
    return [
        event
        for event in events
        if dig(event, "event", "module") != CAPEMON_MODULE or key_of(event) not in elsewhere
    ]


class ProcessAttribution:
    """Answers only when exactly one process explains the key; two candidates mean no answer."""

    def __init__(self, capemon_events: Iterable[Mapping[str, Any]]) -> None:
        self._by_key: dict[Key, list[Mapping[str, Any]]] = {}
        for event in capemon_events:
            key = key_of(event) if "process" in event else None
            if key is not None:
                self._by_key.setdefault(key, []).append(event)

    def lookup(self, key: Key) -> Attribution | None:
        events = self._by_key.get(key, [])
        if len({event["process"]["entity_id"] for event in events}) != 1:
            return None
        earliest = events[0]
        process = {name: value for name, value in earliest["process"].items() if name != "thread"}
        return Attribution(process, earliest["event"]["id"])
