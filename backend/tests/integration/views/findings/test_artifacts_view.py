import json

import pytest

from tests.integration.views.conftest import ViewStack
from tests.integration.views.findings.support import install_report, put_file
from tests.integration.views.helpers import add_analysis_without_index, get_view

pytestmark = pytest.mark.integration

DROPPED_SHA256 = "19e19f9e997696d63c3a2ef193633c001b032b3880fd4b487dfea606aa77c196"
PCAP_SHA256 = "c79656a444d0bd53b8c2b2af439c01c6fe92b4f5f5c38aa09d0519d513d4b7ac"
EMPTY_VIEW = {
    "dropped": [],
    "payloads": [],
    "procdumps": [],
    "memory_dump": None,
    "pcap": None,
    "screenshots": [],
    "configs": [],
}


async def test_the_artifact_list_is_computed_from_the_report(stack: ViewStack) -> None:
    install_report(stack)
    put_file(stack, f"files/{DROPPED_SHA256}", b"tartarus benign sample was here\r\n")

    view = await get_view(stack, "artifacts")

    (dropped,) = view["dropped"]
    assert dropped["name"] == "tartarus-benign.txt"
    assert dropped["sha256"] == DROPPED_SHA256
    assert dropped["size"] == 33
    assert dropped["type"] == "ASCII text, with CRLF line terminators"
    assert dropped["source_process"] == {"pid": 10116, "name": "benign.exe"}
    assert dropped["guest_path"].endswith("tartarus-benign.txt")
    assert dropped["downloadable"] is True
    assert [d["name"] for d in view["procdumps"]] == ["benign.exe", "cmd.exe"]
    assert all(d["downloadable"] is False for d in view["procdumps"])


async def test_payloads_configs_pcap_memory_dump_and_screenshots_are_listed(
    stack: ViewStack,
) -> None:
    report = install_report(stack)
    report["CAPE"] = {
        "payloads": [{"name": "stage2.bin", "sha256": "b" * 64, "size": 7, "pid": 9632}],
        "configs": [{"AsyncRAT": {"Host": "evil.example"}}],
    }
    install_report(stack, report)
    put_file(stack, "CAPE/" + "b" * 64, b"payload")
    put_file(stack, "dump.pcap", b"pcap-bytes")
    put_file(stack, "memory.dmp", b"memory")
    put_file(stack, "shots/0001.jpg", b"jpeg-one")
    put_file(stack, "shots/0002.jpg", b"jpeg-two!")

    view = await get_view(stack, "artifacts")

    (payload,) = view["payloads"]
    assert (payload["name"], payload["size"], payload["downloadable"]) == ("stage2.bin", 7, True)
    assert payload["source_process"]["name"] == "cmd.exe"
    assert view["configs"][0]["family"] == "AsyncRAT"
    assert view["configs"][0]["data"] == {"Host": "evil.example"}
    assert (view["pcap"]["size"], view["pcap"]["sha256"]) == (10, PCAP_SHA256)
    assert view["memory_dump"]["size"] == 6
    assert view["screenshots"] == [
        {"n": 1, "name": "0001.jpg", "size": 8},
        {"n": 2, "name": "0002.jpg", "size": 9},
    ]


async def test_an_artifact_id_is_stable_between_requests_and_is_not_a_path(
    stack: ViewStack,
) -> None:
    install_report(stack)

    first = (await get_view(stack, "artifacts"))["dropped"][0]["id"]
    second = (await get_view(stack, "artifacts"))["dropped"][0]["id"]

    assert first == second
    assert first.isalnum()
    assert "/" not in first
    assert DROPPED_SHA256 not in first


async def test_a_missing_report_gives_empty_collections(stack: ViewStack) -> None:
    assert await get_view(stack, "artifacts") == EMPTY_VIEW


async def test_a_report_that_is_not_json_gives_empty_collections(stack: ViewStack) -> None:
    put_file(stack, "reports/report.json", b"{ not json")

    assert await get_view(stack, "artifacts") == EMPTY_VIEW


async def test_a_report_that_is_not_a_cape_report_gives_empty_collections(
    stack: ViewStack,
) -> None:
    put_file(stack, "reports/report.json", json.dumps({"hello": "world"}).encode())

    assert await get_view(stack, "artifacts") == EMPTY_VIEW


async def test_an_analysis_not_submitted_to_cape_has_no_artifacts(stack: ViewStack) -> None:
    bare = await add_analysis_without_index(stack)

    assert await get_view(stack, "artifacts", bare) == EMPTY_VIEW


async def test_an_unknown_analysis_is_a_404_in_the_error_envelope(stack: ViewStack) -> None:
    response = await stack.client.get("/api/analyses/99999/artifacts")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"
