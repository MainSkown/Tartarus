import hashlib
from pathlib import Path

import pytest

from app.rules.loader import load_rule_file, load_rules
from app.rules.regexes import RegexLimits
from app.rules.rule import Validity
from tests.rules.support import DEFAULT_ID, DEFAULT_RULESET, rule_yaml, simple_detection

SELECTION = simple_detection("Image|endswith: '\\cmd.exe'")


def write(directory: Path, name: str, text: str) -> Path:
    path = directory / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_a_valid_rule_carries_its_metadata(tmp_path: Path) -> None:
    text = rule_yaml(SELECTION, tags=("attack.execution", "attack.t1059.001"), level="high")
    path = write(tmp_path, "a/rule.yml", text)

    rule = load_rule_file(path)

    assert rule.validity is Validity.VALID
    assert rule.error is None
    assert rule.id == DEFAULT_ID
    assert rule.title == "Test rule"
    assert rule.description == "A rule for the tests"
    assert rule.level == "high"
    assert rule.status == "test"
    assert rule.tags == ("attack.execution", "attack.t1059.001")
    assert rule.logsource_category == "process_creation"
    assert rule.path == path
    assert rule.content_sha256 == hashlib.sha256(text.encode()).hexdigest()


def test_load_rules_reads_every_yml_below_the_directory_in_path_order(tmp_path: Path) -> None:
    write(tmp_path, "b/second.yml", rule_yaml(SELECTION, rule_id="2" * 8 + DEFAULT_ID[8:]))
    write(tmp_path, "a/deep/first.yml", rule_yaml(SELECTION, rule_id="1" * 8 + DEFAULT_ID[8:]))
    write(tmp_path, "a/notes.txt", "not a rule")

    rules = load_rules(tmp_path)

    assert [rule.path.name for rule in rules] == ["first.yml", "second.yml"]


def test_a_missing_directory_gives_no_rules(tmp_path: Path) -> None:
    assert load_rules(tmp_path / "absent") == []


def test_invalid_yaml_is_invalid_with_the_error_and_never_raises(tmp_path: Path) -> None:
    rule = load_rule_file(write(tmp_path, "bad.yml", "title: [unclosed\n"))

    assert rule.validity is Validity.INVALID
    assert rule.error


@pytest.mark.parametrize("text", ["- just\n- a list\n", "", "title: only a title\n"])
def test_a_document_that_is_not_a_rule_is_invalid(tmp_path: Path, text: str) -> None:
    rule = load_rule_file(write(tmp_path, "bad.yml", text))

    assert rule.validity is Validity.INVALID
    assert rule.error


def test_a_file_that_is_not_utf8_is_invalid(tmp_path: Path) -> None:
    path = tmp_path / "binary.yml"
    path.write_bytes(b"\xff\xfe\x00bad")

    assert load_rule_file(path).validity is Validity.INVALID


def test_an_invalid_rule_keeps_the_metadata_it_could_read(tmp_path: Path) -> None:
    text = rule_yaml(simple_detection("Image|nosuchmodifier: x"), title="Readable title")
    rule = load_rule_file(write(tmp_path, "r.yml", text))

    assert rule.title == "Readable title"
    assert rule.id == DEFAULT_ID
    assert rule.level == "high"
    assert rule.path.name == "r.yml"


def test_a_rule_without_an_id_gets_a_stable_id_from_its_path(tmp_path: Path) -> None:
    path = write(tmp_path, "noid.yml", rule_yaml(SELECTION, rule_id=None))

    first, second = load_rule_file(path), load_rule_file(path)

    assert first.id == second.id
    assert first.id != DEFAULT_ID


def test_a_missing_level_is_kept_as_none(tmp_path: Path) -> None:
    rule = load_rule_file(write(tmp_path, "r.yml", rule_yaml(SELECTION, level=None)))

    assert rule.level is None


def test_unknown_modifier_is_unsupported_and_names_it(tmp_path: Path) -> None:
    text = rule_yaml(simple_detection("Image|nosuchmodifier: x"))
    rule = load_rule_file(write(tmp_path, "r.yml", text))

    assert rule.validity is Validity.UNSUPPORTED
    assert rule.error is not None
    assert "nosuchmodifier" in rule.error


def test_a_condition_naming_an_undefined_selection_is_invalid(tmp_path: Path) -> None:
    text = rule_yaml(simple_detection("Image: x", "selection and missing"))
    rule = load_rule_file(write(tmp_path, "r.yml", text))

    assert rule.validity is Validity.INVALID
    assert rule.error is not None
    assert "missing" in rule.error


def test_an_aggregation_condition_is_unsupported(tmp_path: Path) -> None:
    text = rule_yaml(simple_detection("Image: x", "selection | count() > 3"))
    rule = load_rule_file(write(tmp_path, "r.yml", text))

    assert rule.validity is Validity.UNSUPPORTED
    assert rule.error is not None
    assert "aggregation" in rule.error


def test_a_correlation_rule_is_unsupported(tmp_path: Path) -> None:
    text = """\
title: Many logins
name: many_logins
correlation:
    type: event_count
    rules:
        - login
    group-by:
        - User
    timespan: 5m
    condition:
        gte: 5
level: high
"""
    rule = load_rule_file(write(tmp_path, "c.yml", text))

    assert rule.validity is Validity.UNSUPPORTED
    assert rule.error is not None
    assert "correlation" in rule.error


def test_a_multi_document_file_is_unsupported(tmp_path: Path) -> None:
    text = rule_yaml(SELECTION) + "---\n" + rule_yaml(SELECTION)
    rule = load_rule_file(write(tmp_path, "multi.yml", text))

    assert rule.validity is Validity.UNSUPPORTED
    assert rule.error is not None
    assert "document" in rule.error


@pytest.mark.parametrize(
    ("category", "product", "fragment"),
    [
        ("image_load", "windows", "image_load"),
        ("process_access", "windows", "process_access"),
        (None, "windows", "category"),
        ("process_creation", "linux", "linux"),
    ],
)
def test_an_unsupported_logsource_says_why(
    tmp_path: Path, category: str | None, product: str, fragment: str
) -> None:
    text = rule_yaml(SELECTION, category=category, product=product)
    rule = load_rule_file(write(tmp_path, "r.yml", text))

    assert rule.validity is Validity.UNSUPPORTED
    assert rule.error is not None
    assert fragment in rule.error


def test_a_rule_with_no_product_is_accepted(tmp_path: Path) -> None:
    rule = load_rule_file(write(tmp_path, "r.yml", rule_yaml(SELECTION, product=None)))

    assert rule.validity is Validity.VALID


def test_the_second_rule_with_a_known_id_is_invalid_and_names_the_first(tmp_path: Path) -> None:
    write(tmp_path, "a.yml", rule_yaml(SELECTION))
    write(tmp_path, "b.yml", rule_yaml(SELECTION))

    first, second = load_rules(tmp_path)

    assert first.validity is Validity.VALID
    assert second.validity is Validity.INVALID
    assert second.error is not None
    assert "a.yml" in second.error


def test_the_shipped_default_ruleset_loads_without_surprises() -> None:
    rules = load_rules(DEFAULT_RULESET)

    assert len(rules) == 60
    assert {rule.validity for rule in rules} == {Validity.VALID}, [
        (rule.path.name, rule.error) for rule in rules if rule.validity is not Validity.VALID
    ]


def test_a_regular_expression_re2_cannot_run_is_invalid_with_its_error(tmp_path: Path) -> None:
    text = rule_yaml(simple_detection("CommandLine|re: '(?=lookahead)x'"))
    rule = load_rule_file(write(tmp_path, "r.yml", text))

    assert rule.validity is Validity.INVALID
    assert rule.error is not None
    assert "lookahead" in rule.error


def test_an_oversized_regular_expression_is_invalid_through_the_loader(tmp_path: Path) -> None:
    text = rule_yaml(simple_detection("CommandLine|re: 'a{1000}'"))
    path = write(tmp_path, "r.yml", text)

    rule = load_rule_file(path, RegexLimits(max_program_bytes=8000))

    assert rule.validity is Validity.INVALID
    assert rule.error is not None
    assert "too large" in rule.error


def test_a_valid_rule_carries_a_predicate_that_runs(tmp_path: Path) -> None:
    rule = load_rule_file(write(tmp_path, "r.yml", rule_yaml(SELECTION)))

    assert rule.predicate is not None
    assert rule.predicate({"process": {"executable": "C:\\Windows\\System32\\CMD.EXE"}})
    assert not rule.predicate({"process": {"executable": "C:\\Windows\\System32\\calc.exe"}})


def test_a_rule_that_is_not_valid_has_no_predicate(tmp_path: Path) -> None:
    text = rule_yaml(simple_detection("Image|fieldref: CommandLine"))

    rule = load_rule_file(write(tmp_path, "r.yml", text))

    assert rule.validity is Validity.UNSUPPORTED
    assert rule.error is not None
    assert "fieldref" in rule.error
    assert rule.predicate is None


def test_references_and_the_condition_text_are_kept(tmp_path: Path) -> None:
    extra = "references:\n    - https://example.com/a\n    - https://example.com/b"
    text = rule_yaml(SELECTION, extra=extra)
    rule = load_rule_file(write(tmp_path, "r.yml", text))

    assert rule.references == ("https://example.com/a", "https://example.com/b")
    assert rule.condition == "selection"


def test_the_author_is_kept_as_the_rule_names_it(tmp_path: Path) -> None:
    text = rule_yaml(SELECTION, extra="author: Florian Roth, Nasreddine Bencherchali")
    rule = load_rule_file(write(tmp_path, "r.yml", text))

    assert rule.author == "Florian Roth, Nasreddine Bencherchali"


def test_a_rule_without_an_author_has_none(tmp_path: Path) -> None:
    rule = load_rule_file(write(tmp_path, "r.yml", rule_yaml(SELECTION)))

    assert rule.author is None


def test_a_list_of_conditions_is_joined(tmp_path: Path) -> None:
    detection = "a:\n  Image: x\nb:\n  Image: y\ncondition:\n  - a\n  - b"
    rule = load_rule_file(write(tmp_path, "r.yml", rule_yaml(detection)))

    assert rule.condition == "a; b"
