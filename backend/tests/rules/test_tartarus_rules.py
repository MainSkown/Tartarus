"""The rules Tartarus ships itself (`rules/sigma/tartarus/`) load valid and fire on real shapes."""

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.ingest.protocol import IngestContext
from app.rules.engine import Emit, SigmaEngine
from app.rules.loader import load_rules
from app.rules.rule import Rule, Validity
from tests.rules.support import TARTARUS_RULESET

FIXTURES = Path(__file__).parent.parent / "fixtures" / "events"
CONTEXT = IngestContext(analysis_id=193, started_at=datetime(2026, 10, 14, 16, 43, tzinfo=UTC))
SELFTEST_RULE_ID = "6c17e2ec-0203-4f72-8760-b1b2a72336db"


@pytest.fixture(scope="module")
def rules() -> list[Rule]:
    return load_rules(TARTARUS_RULESET)


@pytest.fixture
def benign_registry_write() -> dict[str, object]:
    """A `reg-value-set` of the e2e's benign sample, as analysis 193 indexed it."""
    return json.loads((FIXTURES / "benign_reg_value_set.json").read_text())


def test_every_tartarus_rule_is_valid(rules: list[Rule]) -> None:
    assert rules
    assert [(r.path.name, r.validity, r.error) for r in rules] == [
        (r.path.name, Validity.VALID, None) for r in rules
    ]


def test_the_selftest_rule_has_a_fixed_id_and_a_level_that_does_not_alarm(
    rules: list[Rule],
) -> None:
    [rule] = [r for r in rules if r.id == SELFTEST_RULE_ID]
    assert rule.level == "informational"
    assert rule.logsource_category == "registry_set"


def test_the_benign_samples_registry_write_raises_the_selftest_alert(
    rules: list[Rule], benign_registry_write: dict[str, object]
) -> None:
    engine = SigmaEngine(rules, CONTEXT)

    [outcome] = engine.process(benign_registry_write)

    assert isinstance(outcome, Emit)
    assert outcome.detection["rule"]["id"] == SELFTEST_RULE_ID
    assert outcome.detection["related"]["events"] == [benign_registry_write["event"]["id"]]  # type: ignore[index]


def test_another_registry_write_does_not_raise_it(
    rules: list[Rule], benign_registry_write: dict[str, object]
) -> None:
    benign_registry_write["registry"]["path"] = "HKEY_CURRENT_USER\\Software\\Other\\SelfTest"  # type: ignore[index]

    assert SigmaEngine(rules, CONTEXT).process(benign_registry_write) == []
