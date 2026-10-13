from typing import Any

import pytest

from app.views import iocs as ioc_module
from tests.integration.views.conftest import ViewStack
from tests.integration.views.findings.support import install_report
from tests.integration.views.helpers import (
    add_analysis_without_index,
    get_view,
    index_extra_events,
    synthetic_event,
)
from tests.test_analysis_repository import SHA_A

pytestmark = pytest.mark.integration


def of_type(view: dict[str, Any], type_: str) -> list[dict[str, Any]]:
    return [ioc for ioc in view["iocs"] if ioc["type"] == type_]


def connection(event_id: str, ip: str) -> dict[str, Any]:
    return synthetic_event(
        event_id,
        "2026-10-13T12:13:00.000Z",
        "network-connection",
        "network",
        destination={"ip": ip, "port": 443},
    )


def lookup(event_id: str, name: str) -> dict[str, Any]:
    return synthetic_event(
        event_id,
        "2026-10-13T12:13:00.000Z",
        "dns-query",
        "network",
        dns={"question": {"name": name}},
    )


async def test_domains_are_deduplicated_with_a_count_and_their_events(stack: ViewStack) -> None:
    view = await get_view(stack, "iocs")

    domains = {ioc["value"]: ioc for ioc in of_type(view, "domain")}
    assert set(domains) == {
        "tartarus-selftest.example",
        "www.msftconnecttest.com",
        "ipv6.msftconnecttest.com",
        "outlook.office.com",
        "staging.to-do.officeppe.com",
    }
    selftest = domains["tartarus-selftest.example"]
    assert selftest["count"] == 2
    assert len(selftest["source_event_ids"]) == 2
    assert selftest["process"]["name"] == "benign.exe"
    assert "tartarus-selftest.example" in selftest["context"]


async def test_the_sandbox_network_is_not_an_ioc_but_other_addresses_are(
    stack: ViewStack,
) -> None:
    await index_extra_events(
        stack,
        [
            connection("ip-1", "93.184.216.34"),
            connection("ip-2", "93.184.216.34"),
            connection("ip-3", "192.168.150.77"),
            connection("ip-4", "192.168.151.1"),
        ],
    )

    view = await get_view(stack, "iocs")

    assert [(i["value"], i["count"]) for i in of_type(view, "ip")] == [
        ("93.184.216.34", 2),
        ("192.168.151.1", 1),
    ]


async def test_the_fixture_alone_has_no_ip_iocs_because_every_flow_is_the_gateway(
    stack: ViewStack,
) -> None:
    view = await get_view(stack, "iocs")

    assert of_type(view, "ip") == []


async def test_urls_registry_paths_and_file_paths_keep_their_original_case(
    stack: ViewStack,
) -> None:
    view = await get_view(stack, "iocs")

    assert {i["value"] for i in of_type(view, "url")} == {
        "http://www.msftconnecttest.com/connecttest.txt",
        "http://ipv6.msftconnecttest.com/connecttest.txt",
    }
    assert {i["value"] for i in of_type(view, "registry")} == {
        "HKEY_CURRENT_USER\\Software\\Tartarus",
        "HKEY_CURRENT_USER\\Software\\Tartarus\\SelfTest",
    }
    (written,) = of_type(view, "file")
    assert written["value"] == "C:\\Users\\Analyst\\AppData\\Local\\Temp\\tartarus-benign.txt"
    assert written["count"] == 2


async def test_values_that_differ_only_in_case_are_one_indicator(stack: ViewStack) -> None:
    await index_extra_events(
        stack, [lookup("case-1", "Evil.Example"), lookup("case-2", "evil.example")]
    )

    view = await get_view(stack, "iocs")

    (evil,) = [i for i in of_type(view, "domain") if i["value"].lower() == "evil.example"]
    assert evil["count"] == 2
    assert evil["value"] == "Evil.Example"


async def test_an_indicator_lists_at_most_ten_source_events(stack: ViewStack) -> None:
    await index_extra_events(stack, [lookup(f"many-{n}", "busy.example") for n in range(15)])

    view = await get_view(stack, "iocs")

    (busy,) = [i for i in of_type(view, "domain") if i["value"] == "busy.example"]
    assert busy["count"] == 15
    assert len(busy["source_event_ids"]) == 10


async def test_a_type_with_more_values_than_the_limit_is_reported_as_truncated(
    stack: ViewStack, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(ioc_module, "VALUES_PER_TYPE", 2)

    view = await get_view(stack, "iocs")

    assert len(of_type(view, "domain")) == 2
    assert "domain" in view["truncated_types"]
    assert "ip" not in view["truncated_types"]


async def test_the_submitted_sample_is_always_a_hash_ioc(stack: ViewStack) -> None:
    view = await get_view(stack, "iocs")

    (sample,) = of_type(view, "hash")
    assert sample["value"] == SHA_A
    assert "benign.exe" in sample["context"]


async def test_dropped_files_and_mutexes_come_from_the_report(stack: ViewStack) -> None:
    install_report(stack)

    view = await get_view(stack, "iocs")

    hashes = {i["value"]: i for i in of_type(view, "hash")}
    dropped = hashes["19e19f9e997696d63c3a2ef193633c001b032b3880fd4b487dfea606aa77c196"]
    assert dropped["context"] == "Dropped file tartarus-benign.txt"
    assert dropped["process"]["pid"] == 10116
    assert [i["value"] for i in of_type(view, "mutex")] == ["Local\\SM0:9632:304:WilStaging_02"]


async def test_a_hash_seen_twice_is_one_indicator_with_a_count(stack: ViewStack) -> None:
    report = install_report(stack)
    report["dropped"][0]["sha256"] = SHA_A
    install_report(stack, report)

    view = await get_view(stack, "iocs")

    (only,) = of_type(view, "hash")
    assert (only["value"], only["count"]) == (SHA_A, 2)


async def test_indicators_are_ordered_by_type_then_count(stack: ViewStack) -> None:
    install_report(stack)

    view = await get_view(stack, "iocs")

    types = [i["type"] for i in view["iocs"]]
    order = ["hash", "domain", "ip", "url", "mutex", "registry", "file"]
    assert types == sorted(types, key=order.index)
    domains = of_type(view, "domain")
    assert domains[0]["value"] == "tartarus-selftest.example"


async def test_an_analysis_without_an_index_or_report_has_only_its_sample_hash(
    stack: ViewStack,
) -> None:
    bare = await add_analysis_without_index(stack)

    view = await get_view(stack, "iocs", bare)

    assert [(i["type"], i["value"]) for i in view["iocs"]] == [("hash", SHA_A)]
    assert view["truncated_types"] == []


async def test_an_unknown_analysis_is_a_404(stack: ViewStack) -> None:
    response = await stack.client.get("/api/analyses/99999/iocs")

    assert response.status_code == 404
