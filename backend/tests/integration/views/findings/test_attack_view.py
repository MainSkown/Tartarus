import json
from typing import Any

import pytest

from app.views.attack_table import load_attack_table
from tests.ingest.conftest import FULL_REPORT
from tests.integration.views.conftest import ViewStack
from tests.integration.views.findings.support import alert
from tests.integration.views.helpers import add_analysis_without_index, get_view, index_extra_events

pytestmark = pytest.mark.integration


def report_technique_ids() -> set[str]:
    report = json.loads(FULL_REPORT.read_text())
    return {t for entry in report["ttps"] for t in entry["ttps"]}


def hits(matrix: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    return {tactic["id"]: tactic["techniques"] for tactic in matrix["tactics"]}


def tactics_by_technique(matrix: dict[str, Any]) -> dict[str, set[str]]:
    placed: dict[str, set[str]] = {}
    for tactic in matrix["tactics"]:
        for technique in tactic["techniques"]:
            placed.setdefault(technique["id"], set()).add(tactic["id"])
    return placed


async def test_every_technique_of_the_report_appears_under_the_tactics_of_the_table(
    stack: ViewStack,
) -> None:
    matrix = await get_view(stack, "attack")

    placed = tactics_by_technique(matrix)
    table = load_attack_table()
    assert set(placed) == report_technique_ids()
    for technique_id, tactic_ids in placed.items():
        known = table.technique(technique_id)
        assert known is not None
        assert tactic_ids == set(known.tactics)


async def test_process_injection_is_under_the_tactics_the_table_gives_it(stack: ViewStack) -> None:
    matrix = await get_view(stack, "attack")

    injection = {
        tactic["id"]: next(t for t in tactic["techniques"] if t["id"] == "T1055")
        for tactic in matrix["tactics"]
        if any(t["id"] == "T1055" for t in tactic["techniques"])
    }
    assert set(injection) == set(load_attack_table().technique("T1055").tactics)  # type: ignore[union-attr]
    one = next(iter(injection.values()))
    assert one["name"] == "Process Injection"
    assert one["hit_count"] == 2
    assert one["severity"] == "medium"
    assert len(one["detection_ids"]) == 2


async def test_tactics_come_in_kill_chain_order(stack: ViewStack) -> None:
    matrix = await get_view(stack, "attack")

    order = [tactic.id for tactic in load_attack_table().tactics]
    positions = [order.index(tactic["id"]) for tactic in matrix["tactics"]]
    assert positions == sorted(positions)
    assert matrix["attack_version"] == load_attack_table().version


async def test_a_technique_id_the_table_lacks_goes_under_unknown_without_a_name(
    stack: ViewStack,
) -> None:
    await index_extra_events(
        stack, [alert("odd-1", "odd", 3, threat={"technique": {"id": ["T9999"]}})]
    )

    matrix = await get_view(stack, "attack")

    assert matrix["tactics"][-1]["id"] == "unknown"
    assert matrix["tactics"][-1]["techniques"] == [
        {
            "id": "T9999",
            "name": None,
            "hit_count": 1,
            "severity": "high",
            "detection_ids": ["odd-1"],
        }
    ]


async def test_an_analysis_without_an_index_has_an_empty_matrix(stack: ViewStack) -> None:
    bare = await add_analysis_without_index(stack)

    matrix = await get_view(stack, "attack", bare)

    assert matrix["tactics"] == []


async def test_an_unknown_analysis_is_a_404(stack: ViewStack) -> None:
    response = await stack.client.get("/api/analyses/99999/attack")

    assert response.status_code == 404
