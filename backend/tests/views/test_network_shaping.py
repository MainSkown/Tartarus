from typing import Any

from app.views.network import shape_network

PCAP = "cape.network"
CAPEMON = "capemon.derived"
GUEST = {"pid": 7, "name": "evil.exe", "entity_id": "1:7@x"}


def event(action: str, dataset: str, time: str, event_id: str, **sections: Any) -> dict[str, Any]:
    return {
        "@timestamp": time,
        "event": {
            "id": event_id,
            "action": action,
            "dataset": dataset,
            "module": dataset.split(".", maxsplit=1)[0],
        },
        **sections,
    }


def dns(name: str, dataset: str = PCAP, answers: list[str] | None = None, **extra: Any) -> Any:
    question = {"name": name, "type": "A"}
    sections: dict[str, Any] = {"dns": {"question": question}, **extra}
    if answers:
        sections["dns"]["answers"] = {"data": answers}
    return event("dns-query", dataset, "2026-01-01T00:00:01Z", f"dns-{name}-{dataset}", **sections)


def connection(destination: str, port: int, dataset: str = PCAP, **extra: Any) -> dict[str, Any]:
    return event(
        "network-connection",
        dataset,
        "2026-01-01T00:00:02Z",
        f"flow-{destination}-{port}-{dataset}",
        destination={"ip": destination, "port": port},
        source={"ip": "10.0.0.2", "port": 5000},
        network={"transport": "tcp"},
        **extra,
    )


def http(url: str, host: str, dataset: str = PCAP, **extra: Any) -> dict[str, Any]:
    return event(
        "http-request",
        dataset,
        "2026-01-01T00:00:03Z",
        f"http-{url}-{dataset}",
        url={"full": url},
        destination={"domain": host},
        http={"request": {"method": "GET"}},
        **extra,
    )


def shape(events: list[dict[str, Any]], limit: int = 100) -> Any:
    return shape_network(events, simulated=False, limit=limit)


def test_a_lookup_only_capemon_saw_is_kept() -> None:
    view = shape([dns("blocked.example", CAPEMON, process=GUEST)])

    [row] = view.dns.items
    assert (row.query, row.process.pid if row.process else None) == ("blocked.example", 7)


def test_a_capemon_lookup_the_pcap_also_has_is_dropped_whatever_the_case() -> None:
    view = shape([dns("Evil.Example.", CAPEMON, process=GUEST), dns("evil.example")])

    assert [row.query for row in view.dns.items] == ["evil.example"]
    assert view.dns.total == 1


def test_a_capemon_connection_the_pcap_also_has_is_dropped_but_a_different_port_is_kept() -> None:
    view = shape(
        [
            connection("1.2.3.4", 80),
            connection("1.2.3.4", 80, CAPEMON),
            connection("1.2.3.4", 81, CAPEMON),
        ]
    )

    assert [row.destination_port for row in view.flows.items] == [80, 81]


def test_a_capemon_request_the_pcap_also_has_is_dropped() -> None:
    view = shape(
        [http("http://a.example/x", "a.example", CAPEMON), http("http://a.example/x", "a.example")]
    )

    assert view.http.total == 1


def test_rows_are_ordered_by_time_and_cut_at_the_limit_with_the_full_total() -> None:
    events = [connection("9.9.9.9", port) for port in range(1, 8)]

    view = shape(events, limit=3)

    assert [row.destination_port for row in view.flows.items] == [1, 2, 3]
    assert view.flows.total == 7


def test_an_unattributed_row_has_no_process() -> None:
    [row] = shape([connection("1.1.1.1", 53)]).flows.items

    assert row.process is None


def test_an_attributed_row_names_the_process() -> None:
    [row] = shape([dns("evil.example", process=GUEST)]).dns.items

    assert row.process is not None
    assert (row.process.pid, row.process.name) == (7, "evil.exe")


def test_a_host_unites_connections_to_an_address_and_the_names_resolving_to_it() -> None:
    view = shape(
        [
            dns("evil.example", answers=["1.2.3.4"]),
            connection("1.2.3.4", 80),
            connection("1.2.3.4", 443),
            http("http://evil.example/a", "evil.example"),
        ]
    )

    hosts = {row.host: row for row in view.hosts.items}
    assert (hosts["1.2.3.4"].kind, hosts["1.2.3.4"].count, hosts["1.2.3.4"].related) == (
        "ip",
        2,
        ["evil.example"],
    )
    assert (
        hosts["evil.example"].kind,
        hosts["evil.example"].count,
        hosts["evil.example"].related,
    ) == (
        "domain",
        2,
        ["1.2.3.4"],
    )


def test_hosts_are_ordered_by_how_often_they_were_contacted() -> None:
    view = shape([connection("2.2.2.2", 1), connection("3.3.3.3", 1), connection("3.3.3.3", 2)])

    assert [row.host for row in view.hosts.items] == ["3.3.3.3", "2.2.2.2"]


def test_simulated_is_passed_through_and_tls_and_alerts_stay_empty() -> None:
    view = shape_network([], simulated=True, limit=10)

    assert view.simulated is True
    assert (view.tls.items, view.tls.total, view.alerts.items, view.alerts.total) == ([], 0, [], 0)
