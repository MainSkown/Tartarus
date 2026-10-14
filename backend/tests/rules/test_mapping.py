from pathlib import Path

import pytest
from sigma.conditions import ConditionFieldEqualsValueExpression
from sigma.rule import SigmaRule

from app.rules.categories import SUPPORTED_CATEGORIES
from app.rules.loader import load_rule_file
from app.rules.mapping import FIELD_MAPS, map_fields
from app.rules.rule import RuleProblem, Validity
from app.search.fields import field_by_name
from tests.rules.support import rule_yaml, simple_detection


def mapped_leaf_fields(category: str, selection: str) -> list[str]:
    rule = SigmaRule.from_yaml(rule_yaml(simple_detection(selection), category=category, tags=()))
    map_fields(rule, category)
    return [leaf.field for leaf in leaves(rule.detection.parsed_condition[0].parse())]


def leaves(node: object) -> list[ConditionFieldEqualsValueExpression]:
    if isinstance(node, ConditionFieldEqualsValueExpression):
        return [node]
    return [leaf for arg in getattr(node, "args", []) for leaf in leaves(arg)]


CASES = [
    ("process_creation", "Image", "process.executable"),
    ("process_creation", "CommandLine", "process.command_line"),
    ("process_creation", "ParentImage", "process.parent.executable"),
    ("process_creation", "ParentCommandLine", "process.parent.command_line"),
    ("process_creation", "ProcessId", "process.pid"),
    ("process_creation", "ParentProcessId", "process.parent.pid"),
    ("file_event", "TargetFilename", "file.path"),
    ("file_event", "Image", "process.executable"),
    ("file_event", "CommandLine", "process.command_line"),
    ("registry_set", "TargetObject", "registry.path"),
    ("registry_set", "Details", "registry.data.strings"),
    ("registry_add", "TargetObject", "registry.path"),
    ("registry_delete", "TargetObject", "registry.path"),
    ("registry_delete", "Image", "process.executable"),
    ("network_connection", "DestinationIp", "destination.ip"),
    ("network_connection", "DestinationPort", "destination.port"),
    ("network_connection", "SourceIp", "source.ip"),
    ("network_connection", "SourcePort", "source.port"),
    ("network_connection", "DestinationHostname", "destination.domain"),
    ("network_connection", "Image", "process.executable"),
    ("dns_query", "QueryName", "dns.question.name"),
    ("dns_query", "Image", "process.executable"),
    ("create_remote_thread", "SourceImage", "process.executable"),
    ("create_remote_thread", "TargetImage", "tartarus.inject.target_executable"),
    ("create_remote_thread", "SourceProcessId", "process.pid"),
    ("create_remote_thread", "TargetProcessId", "tartarus.inject.target_pid"),
]


@pytest.mark.parametrize(("category", "sigma_name", "ecs_name"), CASES)
def test_a_sigma_name_maps_to_its_ecs_field(category: str, sigma_name: str, ecs_name: str) -> None:
    assert mapped_leaf_fields(category, f"{sigma_name}: x") == [ecs_name]


def test_every_supported_category_has_a_map() -> None:
    assert set(FIELD_MAPS) == SUPPORTED_CATEGORIES


def test_every_mapping_target_is_in_the_field_catalog() -> None:
    targets = {target for table in FIELD_MAPS.values() for target in table.values()}

    for target in sorted(targets):
        assert field_by_name(target), target


@pytest.mark.parametrize(
    ("category", "sigma_name"),
    [
        ("process_creation", "OriginalFileName"),
        ("process_creation", "TargetFilename"),
        ("create_remote_thread", "Image"),
        ("file_event", "QueryName"),
        ("dns_query", "Hashes"),
    ],
)
def test_an_unmapped_field_is_invalid_and_named_not_passed_through(
    category: str, sigma_name: str
) -> None:
    rule = SigmaRule.from_yaml(rule_yaml(simple_detection(f"{sigma_name}: x"), category=category))

    with pytest.raises(RuleProblem) as problem:
        map_fields(rule, category)

    assert problem.value.validity is Validity.INVALID
    assert sigma_name in problem.value.reason
    assert category in problem.value.reason


def test_every_unmapped_field_of_a_rule_is_named() -> None:
    selection = "Image: x\nOriginalFileName: y\nHashes: z"
    rule = SigmaRule.from_yaml(rule_yaml(simple_detection(selection)))

    with pytest.raises(RuleProblem) as problem:
        map_fields(rule, "process_creation")

    assert "OriginalFileName" in problem.value.reason
    assert "Hashes" in problem.value.reason
    assert "Image" not in problem.value.reason


def test_an_unmapped_field_inside_a_not_filter_still_invalidates_the_rule() -> None:
    detection = """\
selection:
    Image: x
filter:
    OriginalFileName: y
condition: selection and not filter
"""
    rule = SigmaRule.from_yaml(rule_yaml(detection))

    with pytest.raises(RuleProblem) as problem:
        map_fields(rule, "process_creation")

    assert "OriginalFileName" in problem.value.reason


def test_a_field_already_named_in_the_catalog_passes_through(tmp_path: Path) -> None:
    path = tmp_path / "ecs.yml"
    path.write_text(rule_yaml(simple_detection("process.executable|endswith: '\\x.exe'")))

    assert load_rule_file(path).validity is Validity.VALID


def test_the_loader_reports_an_unmapped_field_as_invalid(tmp_path: Path) -> None:
    path = tmp_path / "r.yml"
    path.write_text(rule_yaml(simple_detection("OriginalFileName: cmd.exe")))

    rule = load_rule_file(path)

    assert rule.validity is Validity.INVALID
    assert rule.error is not None
    assert "OriginalFileName" in rule.error


@pytest.mark.parametrize(
    ("event_type", "action"),
    [
        ("SetValue", "reg-value-set"),
        ("CreateKey", "reg-key-created"),
        ("DeleteValue", "reg-value-deleted"),
        ("DeleteKey", "reg-key-deleted"),
    ],
)
def test_the_sysmon_event_type_becomes_our_event_action(event_type: str, action: str) -> None:
    category = "registry_delete"
    rule = SigmaRule.from_yaml(
        rule_yaml(simple_detection(f"EventType: {event_type}"), category=category)
    )

    map_fields(rule, category)

    [leaf] = leaves(rule.detection.parsed_condition[0].parse())
    assert leaf.field == "event.action"
    assert str(leaf.value) == action
