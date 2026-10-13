import json
from pathlib import Path

from app.views.attack_table import UNKNOWN_TACTIC, AttackTable, load_attack_table


def test_the_shipped_table_orders_the_kill_chain_from_reconnaissance_to_impact() -> None:
    tactic_ids = [tactic.id for tactic in load_attack_table().tactics]

    assert tactic_ids[0] == "reconnaissance"
    assert tactic_ids[-1] == "impact"
    assert len(tactic_ids) == len(set(tactic_ids))


def test_the_shipped_table_names_a_technique_and_a_sub_technique() -> None:
    table = load_attack_table()

    assert table.technique("T1055") is not None
    assert table.technique("T1059.001") is not None
    assert table.technique("T1059.001").name == "PowerShell"  # type: ignore[union-attr]


def test_process_injection_is_a_privilege_escalation_technique() -> None:
    injection = load_attack_table().technique("T1055")

    assert injection is not None
    assert "privilege-escalation" in injection.tactics


def test_every_technique_tactic_is_a_tactic_of_the_table() -> None:
    table = load_attack_table()
    known = {tactic.id for tactic in table.tactics}

    assert all(set(info.tactics) <= known for info in table.techniques.values())


def test_the_table_records_its_attack_version() -> None:
    table = load_attack_table()

    assert table.version
    assert table.modified


def test_an_id_absent_from_the_table_is_unknown_not_an_error() -> None:
    assert load_attack_table().technique("T9999") is None


def test_tactic_names_are_display_names() -> None:
    table = load_attack_table()

    assert table.tactic_name("command-and-control") == "Command and Control"
    assert table.tactic_name(UNKNOWN_TACTIC) == "Unknown"


def test_a_table_reads_from_a_file(tmp_path: Path) -> None:
    path = tmp_path / "table.json"
    path.write_text(
        json.dumps(
            {
                "version": "1.0",
                "modified": "2026-01-01",
                "source": "x",
                "tactics": [{"id": "execution", "name": "Execution"}],
                "techniques": {"T1": {"name": "One", "tactics": ["execution"]}},
            }
        )
    )

    table = AttackTable.from_file(path)

    assert table.technique("T1").tactics == ("execution",)  # type: ignore[union-attr]
