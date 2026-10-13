from typing import Any

import pytest

from tests.integration.views.conftest import ViewStack
from tests.integration.views.fixture_events import BENIGN_PID, events_where
from tests.integration.views.helpers import (
    add_analysis_without_index,
    get_view,
    set_route,
)

pytestmark = pytest.mark.integration

PCAP_DATASET = "cape.network"
DNS_NAMES = {
    "www.msftconnecttest.com",
    "ipv6.msftconnecttest.com",
    "outlook.office.com",
    "staging.to-do.officeppe.com",
    "tartarus-selftest.example",
}


async def network(stack: ViewStack, query: str = "") -> dict[str, Any]:
    return await get_view(stack, f"network{query}")


def pcap_events(action: str) -> list[dict[str, Any]]:
    return events_where(
        lambda event: (
            event["event"]["action"] == action and event["event"]["dataset"] == PCAP_DATASET
        )
    )


async def test_dns_rows_are_the_distinct_lookups_with_their_answers(view_stack: ViewStack) -> None:
    dns = (await network(view_stack))["dns"]

    assert dns["total"] == 5
    assert {row["query"] for row in dns["items"]} == DNS_NAMES
    answered = next(row for row in dns["items"] if row["query"] == "www.msftconnecttest.com")
    assert answered["answers"] == ["192.168.150.1"]
    assert answered["type"] == "A"
    assert next(r for r in dns["items"] if r["query"] == "outlook.office.com")["answers"] == []


async def test_the_capemon_copy_of_a_lookup_is_not_listed_twice(view_stack: ViewStack) -> None:
    dns = (await network(view_stack))["dns"]

    assert [row["query"] for row in dns["items"]].count("tartarus-selftest.example") == 1


async def test_http_rows_carry_method_url_host_and_agent(view_stack: ViewStack) -> None:
    http = (await network(view_stack))["http"]

    assert http["total"] == 2
    row = next(r for r in http["items"] if r["host"] == "www.msftconnecttest.com")
    assert row["method"] == "GET"
    assert row["url"] == "http://www.msftconnecttest.com/connecttest.txt"
    assert row["user_agent"] == "Microsoft NCSI"
    assert row["status"] is None


async def test_flows_are_every_connection_in_the_pcap(view_stack: ViewStack) -> None:
    flows = (await network(view_stack))["flows"]

    expected = pcap_events("network-connection")
    assert flows["total"] == len(expected) > 150
    assert len(flows["items"]) == len(expected)
    first = flows["items"][0]
    assert first["transport"] == "tcp"
    assert (first["source_ip"], first["source_port"]) == ("192.168.150.10", 65521)
    assert (first["destination_ip"], first["destination_port"]) == ("192.168.150.1", 443)


async def test_only_the_lookup_the_normaliser_attributed_names_a_process(
    view_stack: ViewStack,
) -> None:
    view = await network(view_stack)

    attributed = [row for row in view["dns"]["items"] if row["process"] is not None]
    assert [(row["query"], row["process"]) for row in attributed] == [
        ("tartarus-selftest.example", {"pid": BENIGN_PID, "name": "benign.exe"})
    ]
    assert all(row["process"] is None for row in view["http"]["items"])
    assert all(row["process"] is None for row in view["flows"]["items"])


async def test_tls_and_alerts_are_empty_lists_until_suricata_arrives(
    view_stack: ViewStack,
) -> None:
    view = await network(view_stack)

    assert view["tls"] == {"items": [], "total": 0}
    assert view["alerts"] == {"items": [], "total": 0}


async def test_hosts_count_connections_and_link_names_with_addresses(
    view_stack: ViewStack,
) -> None:
    hosts = (await network(view_stack))["hosts"]

    by_host = {row["host"]: row for row in hosts["items"]}
    gateway = by_host["192.168.150.1"]
    assert gateway["kind"] == "ip"
    assert gateway["count"] == len(
        [e for e in pcap_events("network-connection") if e["destination"]["ip"] == "192.168.150.1"]
    )
    assert gateway["related"] == ["www.msftconnecttest.com"]
    named = by_host["www.msftconnecttest.com"]
    assert named["kind"] == "domain"
    assert named["related"] == ["192.168.150.1"]
    assert named["count"] == 2
    assert hosts["total"] == len(hosts["items"])


async def test_the_analysis_is_simulated_when_it_routed_through_inetsim(
    view_stack: ViewStack,
) -> None:
    assert (await network(view_stack))["simulated"] is True

    await set_route(view_stack, "none")

    assert (await network(view_stack))["simulated"] is False


async def test_limit_cuts_every_list_but_the_total_still_counts_all(
    view_stack: ViewStack,
) -> None:
    view = await network(view_stack, "?limit=10")

    assert len(view["flows"]["items"]) == 10
    assert view["flows"]["total"] > 150
    assert len(view["dns"]["items"]) == 5
    assert view["dns"]["total"] == 5


async def test_a_limit_below_one_is_rejected(view_stack: ViewStack) -> None:
    response = await view_stack.client.get(
        f"/api/analyses/{view_stack.analysis_id}/network?limit=0"
    )

    assert response.status_code == 422


async def test_an_unknown_analysis_is_a_404(view_stack: ViewStack) -> None:
    response = await view_stack.client.get("/api/analyses/99999/network")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


async def test_an_analysis_without_an_index_has_empty_lists(view_stack: ViewStack) -> None:
    bare = await add_analysis_without_index(view_stack)

    view = await get_view(view_stack, "network", bare)

    empty = {"items": [], "total": 0}
    assert [view[name] for name in ("dns", "http", "tls", "flows", "alerts", "hosts")] == [
        empty
    ] * 6
    assert view["simulated"] is True
