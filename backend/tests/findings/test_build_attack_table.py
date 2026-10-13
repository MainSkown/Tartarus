import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

SCRIPT = Path(__file__).parents[3] / "scripts" / "build-attack-table.py"
SOURCE = "https://example.test/enterprise-attack.json"


def load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("build_attack_table", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def tactic(shortname: str, name: str) -> dict[str, Any]:
    return {
        "type": "x-mitre-tactic",
        "id": f"x-mitre-tactic--{shortname}",
        "name": name,
        "x_mitre_shortname": shortname,
    }


def technique(external_id: str, name: str, phases: list[str], **flags: bool) -> dict[str, Any]:
    return {
        "type": "attack-pattern",
        "name": name,
        "external_references": [
            {"source_name": "mitre-attack", "external_id": external_id},
            {"source_name": "a blog", "external_id": "NOT-THIS"},
        ],
        "kill_chain_phases": [
            {"kill_chain_name": "mitre-attack", "phase_name": phase} for phase in phases
        ],
        **flags,
    }


@pytest.fixture
def bundle() -> dict[str, Any]:
    return {
        "type": "bundle",
        "objects": [
            {
                "type": "x-mitre-collection",
                "x_mitre_version": "19.2",
                "modified": "2026-08-05T21:33:58.496Z",
            },
            {
                "type": "x-mitre-matrix",
                "tactic_refs": ["x-mitre-tactic--execution", "x-mitre-tactic--impact"],
            },
            tactic("impact", "Impact"),
            tactic("execution", "Execution"),
            technique("T1486", "Data Encrypted for Impact", ["impact"]),
            technique("T1059", "Command and Scripting Interpreter", ["execution", "impact"]),
            technique("T1059.001", "PowerShell", ["execution"], x_mitre_is_subtechnique=True),
            technique("T1000", "Old", ["execution"], x_mitre_deprecated=True),
            technique("T1001", "Gone", ["execution"], revoked=True),
        ],
    }


def test_techniques_and_sub_techniques_are_keyed_by_their_attack_id(
    bundle: dict[str, Any],
) -> None:
    table = load_script().build_table(bundle, SOURCE)

    assert table["techniques"]["T1059.001"] == {"name": "PowerShell", "tactics": ["execution"]}
    assert table["techniques"]["T1486"]["name"] == "Data Encrypted for Impact"


def test_deprecated_and_revoked_techniques_are_left_out(bundle: dict[str, Any]) -> None:
    table = load_script().build_table(bundle, SOURCE)

    assert set(table["techniques"]) == {"T1486", "T1059", "T1059.001"}


def test_a_technique_lists_its_tactics_in_kill_chain_order(bundle: dict[str, Any]) -> None:
    bundle["objects"][5]["kill_chain_phases"].reverse()

    table = load_script().build_table(bundle, SOURCE)

    assert table["techniques"]["T1059"]["tactics"] == ["execution", "impact"]


def test_tactics_come_in_the_order_of_the_matrix_with_display_names(
    bundle: dict[str, Any],
) -> None:
    table = load_script().build_table(bundle, SOURCE)

    assert table["tactics"] == [
        {"id": "execution", "name": "Execution"},
        {"id": "impact", "name": "Impact"},
    ]


def test_the_table_records_where_and_which_version_it_came_from(bundle: dict[str, Any]) -> None:
    table = load_script().build_table(bundle, SOURCE)

    assert (table["version"], table["modified"], table["source"]) == (
        "19.2",
        "2026-08-05",
        SOURCE,
    )


def test_a_bundle_without_a_matrix_is_refused(bundle: dict[str, Any]) -> None:
    bundle["objects"] = [o for o in bundle["objects"] if o["type"] != "x-mitre-matrix"]

    with pytest.raises(ValueError, match="matrix"):
        load_script().build_table(bundle, SOURCE)
