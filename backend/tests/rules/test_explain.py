"""`tartarus.detection.match` of a Sigma alert names what matched in the triggering event."""

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from app.ingest.protocol import IngestContext
from app.rules.engine import Emit, SigmaEngine
from app.rules.loader import load_rule_file
from tests.rules.support import process_event, rule_yaml

CONTEXT = IngestContext(analysis_id=7, started_at=datetime(2026, 10, 13, 9, 0, tzinfo=UTC))
PROCESS_FIELDS = {
    "process.executable": "C:\\Windows\\System32\\cmd.exe",
    "process.command_line": "cmd.exe /c whoami",
}


def event_with(action: str = "process-created", **fields: Any) -> dict[str, Any]:
    document = process_event(action=action)
    for dotted, value in fields.items():
        *parents, leaf = dotted.split(".")
        node: dict[str, Any] = document
        for parent in parents:
            node = node.setdefault(parent, {})
        node[leaf] = value
    return document


def alert_of(
    tmp_path: Path, detection: str, document: dict[str, Any], category: str = "process_creation"
) -> dict[str, Any]:
    path = tmp_path / "rule.yml"
    path.write_text(rule_yaml(detection, category=category), encoding="utf-8")
    [outcome] = SigmaEngine([load_rule_file(path)], CONTEXT).process(document)
    assert isinstance(outcome, Emit)
    return outcome.detection


def match_of(
    tmp_path: Path, detection: str, document: dict[str, Any], category: str = "process_creation"
) -> str:
    return str(alert_of(tmp_path, detection, document, category)["tartarus"]["detection"]["match"])


def test_an_equals_leaf_names_the_field_and_the_events_value(tmp_path: Path) -> None:
    detection = """
        selection:
            Image: 'C:\\Windows\\System32\\CMD.exe'
        condition: selection
    """

    match = match_of(tmp_path, detection, event_with(**PROCESS_FIELDS))

    assert match == "process.executable: C:\\Windows\\System32\\cmd.exe"


@pytest.mark.parametrize("modifier", ["contains", "startswith", "endswith", "re"])
def test_each_string_modifier_reports_the_event_value_not_the_rules_pattern(
    tmp_path: Path, modifier: str
) -> None:
    pattern = {
        "contains": "WHOAMI",
        "startswith": "CMD.EXE /c",
        "endswith": "/C WHOAMI",
        "re": "who.+i$",
    }[modifier]
    detection = f"""
        selection:
            CommandLine|{modifier}: '{pattern}'
        condition: selection
    """

    match = match_of(tmp_path, detection, event_with(**PROCESS_FIELDS))

    assert match == "process.command_line: cmd.exe /c whoami"


def test_a_cidr_leaf_reports_the_address_of_the_event(tmp_path: Path) -> None:
    detection = """
        selection:
            DestinationIp|cidr: 10.1.0.0/16
        condition: selection
    """
    document = event_with("network-connection", **{"destination.ip": "10.1.2.3"})

    match = match_of(tmp_path, detection, document, "network_connection")

    assert match == "destination.ip: 10.1.2.3"


def test_a_numeric_comparison_reports_the_number_of_the_event(tmp_path: Path) -> None:
    detection = """
        selection:
            DestinationPort|gt: 1024
        condition: selection
    """
    document = event_with("network-connection", **{"destination.port": 4444})

    match = match_of(tmp_path, detection, document, "network_connection")

    assert match == "destination.port: 4444"


def test_a_windash_leaf_reports_the_variant_the_event_has(tmp_path: Path) -> None:
    detection = """
        selection:
            CommandLine|windash|contains: ' -enc '
        condition: selection
    """

    match = match_of(
        tmp_path, detection, event_with(**{"process.command_line": "powershell /enc AAAA"})
    )

    assert match == "process.command_line: powershell /enc AAAA"


def test_a_list_valued_field_reports_only_the_elements_that_matched(tmp_path: Path) -> None:
    detection = """
        selection:
            Details|contains: 'evil'
        condition: selection
    """
    document = event_with(
        "reg-value-set", **{"registry.data.strings": ["harmless", "evil.exe", "also-evil", "x"]}
    )

    match = match_of(tmp_path, detection, document, "registry_set")

    assert match == "registry.data.strings: evil.exe; registry.data.strings: also-evil"


def test_an_and_condition_lists_every_leaf(tmp_path: Path) -> None:
    detection = """
        selection:
            Image|endswith: '\\cmd.exe'
            CommandLine|contains: whoami
        condition: selection
    """

    match = match_of(tmp_path, detection, event_with(**PROCESS_FIELDS))

    assert match == (
        "process.executable: C:\\Windows\\System32\\cmd.exe; "
        "process.command_line: cmd.exe /c whoami"
    )


def test_an_or_condition_lists_only_the_branches_that_held(tmp_path: Path) -> None:
    detection = """
        by_image:
            Image|endswith: '\\powershell.exe'
        by_command:
            CommandLine|contains: whoami
        condition: by_image or by_command
    """

    match = match_of(tmp_path, detection, event_with(**PROCESS_FIELDS))

    assert match == "process.command_line: cmd.exe /c whoami"


def test_an_or_condition_lists_every_branch_that_held(tmp_path: Path) -> None:
    detection = """
        by_image:
            Image|endswith: '\\cmd.exe'
        by_command:
            CommandLine|contains: whoami
        condition: by_image or by_command
    """

    match = match_of(tmp_path, detection, event_with(**PROCESS_FIELDS))

    assert match.count("; ") == 1


def test_a_list_of_values_under_one_field_reports_the_value_that_matched(
    tmp_path: Path,
) -> None:
    detection = """
        selection:
            CommandLine|contains:
                - mimikatz
                - whoami
        condition: selection
    """

    match = match_of(tmp_path, detection, event_with(**PROCESS_FIELDS))

    assert match == "process.command_line: cmd.exe /c whoami"


def test_a_not_filter_that_held_by_absence_is_not_listed(tmp_path: Path) -> None:
    detection = """
        selection:
            CommandLine|contains: whoami
        filter:
            Image|endswith: '\\explorer.exe'
        condition: selection and not filter
    """

    match = match_of(tmp_path, detection, event_with(**PROCESS_FIELDS))

    assert match == "process.command_line: cmd.exe /c whoami"


def test_one_of_a_pattern_lists_the_leaves_of_the_selections_that_held(tmp_path: Path) -> None:
    detection = """
        selection_image:
            Image|endswith: '\\cmd.exe'
        selection_command:
            CommandLine|contains: whoami
        selection_parent:
            ParentImage|endswith: '\\winword.exe'
        condition: 1 of selection*
    """

    match = match_of(tmp_path, detection, event_with(**PROCESS_FIELDS))

    assert match == (
        "process.executable: C:\\Windows\\System32\\cmd.exe; "
        "process.command_line: cmd.exe /c whoami"
    )


def test_all_of_them_lists_all_the_leaves(tmp_path: Path) -> None:
    detection = """
        a:
            Image|endswith: '\\cmd.exe'
        b:
            CommandLine|contains: whoami
        condition: all of them
    """

    match = match_of(tmp_path, detection, event_with(**PROCESS_FIELDS))

    assert match.count("; ") == 1


def test_a_null_leaf_adds_no_piece(tmp_path: Path) -> None:
    detection = """
        selection:
            CommandLine|contains: whoami
            ParentImage: null
        condition: selection
    """

    match = match_of(tmp_path, detection, event_with(**PROCESS_FIELDS))

    assert match == "process.command_line: cmd.exe /c whoami"


def test_an_exists_leaf_reports_the_value_it_found(tmp_path: Path) -> None:
    detection = """
        selection:
            CommandLine|exists: true
        condition: selection
    """

    match = match_of(tmp_path, detection, event_with(**PROCESS_FIELDS))

    assert match == "process.command_line: cmd.exe /c whoami"


def test_identical_pieces_appear_once(tmp_path: Path) -> None:
    detection = """
        a:
            CommandLine|contains: whoami
        b:
            CommandLine|contains: cmd
        condition: a or b
    """

    match = match_of(tmp_path, detection, event_with(**PROCESS_FIELDS))

    assert match == "process.command_line: cmd.exe /c whoami"


def test_a_long_value_is_cut_to_120_characters_with_an_ellipsis(tmp_path: Path) -> None:
    detection = """
        selection:
            CommandLine|contains: needle
        condition: selection
    """

    match = match_of(
        tmp_path, detection, event_with(**{"process.command_line": "needle" + "x" * 500})
    )

    value = match.removeprefix("process.command_line: ")
    assert len(value) == 120
    assert value.endswith("…")
    assert value.startswith("needlexxx")


def test_the_whole_text_is_cut_to_300_characters_with_an_ellipsis(tmp_path: Path) -> None:
    detection = """
        a:
            CommandLine|contains: needle
        b:
            Image|contains: needle
        c:
            ParentImage|contains: needle
        d:
            ParentCommandLine|contains: needle
        condition: a and b and c and d
    """
    long_value = "needle" + "x" * 500
    document = event_with(
        **{
            "process.command_line": long_value,
            "process.executable": long_value,
            "process.parent.executable": long_value,
            "process.parent.command_line": long_value,
        }
    )

    match = match_of(tmp_path, detection, document)

    assert len(match) == 300
    assert match.endswith("…")


def test_a_rule_with_nothing_to_list_falls_back_to_the_condition_text(tmp_path: Path) -> None:
    detection = """
        selection:
            ParentImage: null
        condition: selection
    """

    match = match_of(tmp_path, detection, event_with(**PROCESS_FIELDS))

    assert match == "selection"


def test_the_same_event_gives_the_same_match_every_time(tmp_path: Path) -> None:
    detection = """
        selection:
            CommandLine|contains:
                - whoami
                - cmd
            Image|endswith: '\\cmd.exe'
        condition: selection
    """
    document = event_with(**PROCESS_FIELDS)

    first = alert_of(tmp_path, detection, document)
    second = alert_of(tmp_path, detection, document)

    assert first == second
