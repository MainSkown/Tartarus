"""Which process did a network record come from, when the capemon events say so exactly."""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from app.ingest.reading import to_int

DNS_QUERY = "dns-query"
NETWORK_CONNECTION = "network-connection"
HTTP_REQUEST = "http-request"

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


def _key_of(event: Mapping[str, Any]) -> Key | None:
    action = event["event"]["action"]
    if action == DNS_QUERY:
        name = event.get("dns", {}).get("question", {}).get("name")
        return dns_key(name) if name else None
    if action == NETWORK_CONNECTION:
        destination = event.get("destination", {})
        address = destination.get("ip")
        return endpoint_key(address, to_int(destination.get("port"))) if address else None
    if action == HTTP_REQUEST:
        url = event.get("url", {}).get("full")
        return url_key(url) if url else None
    return None


class ProcessAttribution:
    """Answers only when exactly one process explains the key; two candidates mean no answer."""

    def __init__(self, capemon_events: Iterable[Mapping[str, Any]]) -> None:
        self._by_key: dict[Key, list[Mapping[str, Any]]] = {}
        for event in capemon_events:
            key = _key_of(event) if "process" in event else None
            if key is not None:
                self._by_key.setdefault(key, []).append(event)

    def lookup(self, key: Key) -> Attribution | None:
        events = self._by_key.get(key, [])
        if len({event["process"]["entity_id"] for event in events}) != 1:
            return None
        earliest = events[0]
        process = {name: value for name, value in earliest["process"].items() if name != "thread"}
        return Attribution(process, earliest["event"]["id"])
