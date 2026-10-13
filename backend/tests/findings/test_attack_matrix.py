from dataclasses import replace

from app.db.models.analysis import Severity
from app.views.attack import AlertTechniques, build_matrix
from app.views.attack_table import AttackTable, Tactic, TechniqueInfo

TABLE = AttackTable(
    version="9.9",
    modified="2026-01-01",
    tactics=(
        Tactic("execution", "Execution"),
        Tactic("stealth", "Stealth"),
        Tactic("impact", "Impact"),
    ),
    techniques={
        "T1059": TechniqueInfo("Command Interpreter", ("execution",)),
        "T1055": TechniqueInfo("Process Injection", ("stealth", "execution")),
        "T1486": TechniqueInfo("Data Encrypted for Impact", ("impact",)),
    },
)


def alert(detection_id: str, severity: Severity, *technique_ids: str) -> AlertTechniques:
    return AlertTechniques(detection_id, severity, technique_ids)


def tactic_ids(alerts: list[AlertTechniques]) -> list[str]:
    return [tactic.id for tactic in build_matrix(alerts, TABLE).tactics]


def test_a_technique_is_listed_under_every_one_of_its_tactics() -> None:
    matrix = build_matrix([alert("d1", Severity.HIGH, "T1055")], TABLE)

    assert [(t.id, [x.id for x in t.techniques]) for t in matrix.tactics] == [
        ("execution", ["T1055"]),
        ("stealth", ["T1055"]),
    ]


def test_tactics_follow_the_kill_chain_order_of_the_table() -> None:
    alerts = [alert("d1", Severity.LOW, "T1486"), alert("d2", Severity.LOW, "T1059")]

    assert tactic_ids(alerts) == ["execution", "impact"]


def test_tactics_without_a_hit_are_left_out() -> None:
    assert tactic_ids([]) == []


def test_a_technique_counts_the_detections_that_raised_it() -> None:
    alerts = [
        alert("d1", Severity.LOW, "T1059"),
        alert("d2", Severity.CRITICAL, "T1059"),
        alert("d3", Severity.HIGH, "T1486"),
    ]

    (execution, _) = build_matrix(alerts, TABLE).tactics
    hit = execution.techniques[0]

    assert (hit.id, hit.name, hit.hit_count, hit.detection_ids) == (
        "T1059",
        "Command Interpreter",
        2,
        ["d1", "d2"],
    )
    assert hit.severity is Severity.CRITICAL


def test_an_alert_naming_a_technique_twice_counts_once() -> None:
    matrix = build_matrix([alert("d1", Severity.LOW, "T1059", "T1059")], TABLE)

    assert matrix.tactics[0].techniques[0].hit_count == 1


def test_an_id_missing_from_the_table_goes_under_unknown_without_a_name() -> None:
    matrix = build_matrix([alert("d1", Severity.MEDIUM, "T9999", "T1059")], TABLE)

    unknown = matrix.tactics[-1]
    assert (unknown.id, unknown.name) == ("unknown", "Unknown")
    assert [(t.id, t.name, t.hit_count) for t in unknown.techniques] == [("T9999", None, 1)]
    assert matrix.tactics[0].id == "execution"


def test_techniques_within_a_tactic_are_ordered_by_id() -> None:
    alerts = [alert("d1", Severity.LOW, "T1059.001", "T1059.003", "T1059")]
    sub_techniques = {
        sub_id: TechniqueInfo(sub_id, ("execution",)) for sub_id in ("T1059.001", "T1059.003")
    }
    table = replace(TABLE, techniques={**TABLE.techniques, **sub_techniques})

    ids = [t.id for t in build_matrix(alerts, table).tactics[0].techniques]

    assert ids == ["T1059", "T1059.001", "T1059.003"]


def test_the_matrix_says_which_attack_release_named_the_techniques() -> None:
    assert build_matrix([], TABLE).attack_version == "9.9"
