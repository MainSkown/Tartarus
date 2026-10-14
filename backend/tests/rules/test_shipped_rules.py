"""Every rule of the shipped default ruleset fires on an event built from its own selection."""

import functools
from datetime import UTC, datetime
from typing import Any

import pytest
from sigma.rule import SigmaRule

from app.ingest.protocol import IngestContext
from app.rules.engine import Emit, SigmaEngine
from app.rules.loader import load_rules
from app.rules.mapping import map_fields
from app.rules.matcher import RuleMatcher
from app.rules.rule import Rule, Validity
from tests.rules.support import DEFAULT_RULESET
from tests.rules.witness import (
    CannotSatisfy,
    alternatives,
    event_fields,
    negated_parts,
)

CONTEXT = IngestContext(analysis_id=7, started_at=datetime(2026, 10, 13, 9, 0, tzinfo=UTC))
ACTIONS = {
    "process_creation": "process-created",
    "file_event": "file-created",
    "registry_set": "reg-value-set",
    "registry_add": "reg-key-created",
    "registry_delete": "reg-value-deleted",
    "dns_query": "dns-query",
    "create_remote_thread": "inject-thread",
    "network_connection": "network-connection",
}
LANES = {
    "process_creation": "process",
    "file_event": "file",
    "registry_set": "registry",
    "registry_add": "registry",
    "registry_delete": "registry",
    "dns_query": "network",
    "create_remote_thread": "process",
}
LIST_FIELDS = {"registry.data.strings"}

# Rules the helper cannot satisfy on its own, written by hand: field values for an event that
# the rule should match.
HAND_WRITTEN: dict[str, dict[str, Any]] = {
    # A `not` filter says `Image: null`, so the event must name a process the other filters
    # do not exclude; derived events carry no `process.executable` and are filtered out.
    "dns_query_win_dns_server_discovery_via_ldap_query": {
        "dns.question.name": "_ldap._tcp.dc._msdcs.corp.example",
        "process.executable": "C:\\Users\\Public\\tool.exe",
    },
}


@functools.cache
def shipped_rules() -> tuple[Rule, ...]:
    return tuple(load_rules(DEFAULT_RULESET))


def rule_ids() -> list[str]:
    return [rule.path.stem for rule in shipped_rules()]


def rule_named(stem: str) -> Rule:
    return next(rule for rule in shipped_rules() if rule.path.stem == stem)


def mapped_tree(rule: Rule) -> object:
    assert rule.logsource_category
    sigma = SigmaRule.from_yaml(rule.path.read_text(encoding="utf-8"))
    map_fields(sigma, rule.logsource_category)
    return sigma.detection.parsed_condition[0].parse()


def build_event(rule: Rule, fields: dict[str, Any]) -> dict[str, Any]:
    category = rule.logsource_category
    assert category
    document: dict[str, Any] = {
        "@timestamp": "2026-10-13T10:00:00.000Z",
        "event": {"id": f"evt-{rule.path.stem}", "kind": "event", "action": ACTIONS[category]},
        "tartarus": {"analysis_id": 7, "lane": LANES.get(category, "process")},
        "process": {"entity_id": "7:100@2026-10-13T09:59:00.000Z", "pid": 100},
    }
    for dotted, value in fields.items():
        *parents, leaf = dotted.split(".")
        node = document
        for parent in parents:
            node = node.setdefault(parent, {})
        node[leaf] = [value] if dotted in LIST_FIELDS else value
    return document


def fires(rule: Rule, document: dict[str, Any]) -> bool:
    return rule.predicate is not None and rule.predicate(document)


def derived_fields(rule: Rule) -> dict[str, Any] | None:
    """The first derived assignment that makes the rule fire, or `None` if the helper has none."""
    try:
        for assignment in alternatives(mapped_tree(rule)):
            fields = event_fields(assignment)
            if fires(rule, build_event(rule, fields)):
                return fields
    except CannotSatisfy:
        return None
    return None


def firing_fields(rule: Rule) -> dict[str, Any]:
    stem = rule.path.stem
    if stem in HAND_WRITTEN:
        return HAND_WRITTEN[stem]
    fields = derived_fields(rule)
    assert fields is not None, f"{stem}: derive no event from the selection; write one by hand"
    return fields


def test_the_default_ruleset_is_all_sixty_rules_and_all_valid() -> None:
    rules = shipped_rules()

    assert len(rules) == 60
    assert {rule.validity for rule in rules} == {Validity.VALID}


def test_the_hand_written_events_are_only_for_rules_the_helper_cannot_do() -> None:
    stale = [stem for stem in HAND_WRITTEN if derived_fields(rule_named(stem)) is not None]

    assert stale == []


@pytest.mark.parametrize("stem", rule_ids())
def test_a_shipped_rule_fires_on_an_event_built_from_its_own_selection(stem: str) -> None:
    rule = rule_named(stem)
    document = build_event(rule, firing_fields(rule))

    outcomes = SigmaEngine([rule], CONTEXT).process(document)

    assert [type(o) for o in outcomes] == [Emit]
    assert isinstance(outcomes[0], Emit)
    assert outcomes[0].detection["rule"]["id"] == rule.id
    assert rule in RuleMatcher(shipped_rules()).match(document)


@pytest.mark.parametrize("stem", rule_ids())
def test_a_shipped_rule_does_not_fire_without_one_of_the_fields_it_needs(stem: str) -> None:
    rule = rule_named(stem)
    fields = firing_fields(rule)
    assert fields

    still_firing = [
        name
        for name in fields
        if fires(rule, build_event(rule, {k: v for k, v in fields.items() if k != name}))
    ]

    assert len(still_firing) < len(fields), f"{stem}: every field is optional: {still_firing}"


def filter_events(rule: Rule) -> list[dict[str, Any]]:
    """Firing events with the fields of a `not` filter added; only fields the event lacks, so the
    selection still holds and the filter alone is what should stop the rule."""
    fields = firing_fields(rule)
    events = []
    for negated in negated_parts(mapped_tree(rule)):
        try:
            candidates = [event_fields(a) for a in alternatives(negated)]
        except CannotSatisfy:
            continue
        events += [
            build_event(rule, {**fields, **candidate})
            for candidate in candidates
            if candidate and not candidate.keys() & fields.keys()
        ]
    return events


def test_a_shipped_rule_with_a_not_filter_stays_quiet_when_the_filter_holds() -> None:
    tested = 0
    for rule in shipped_rules():
        events = filter_events(rule)
        tested += bool(events)
        for document in events:
            assert not fires(rule, document), rule.path.stem
    assert tested >= 5


def test_the_null_filter_of_the_ldap_rule_is_what_an_event_without_a_process_trips() -> None:
    rule = rule_named("dns_query_win_dns_server_discovery_via_ldap_query")
    without_process = build_event(rule, {"dns.question.name": "_ldap._tcp.dc._msdcs.corp.example"})
    named_process = build_event(rule, firing_fields(rule))

    assert not fires(rule, without_process)
    assert fires(rule, named_process)


RULES_NAMING_THE_REGISTRY_OPERATION = [
    "registry_delete_enable_windows_recall",
    "registry_delete_exploit_guard_protected_folders",
    "registry_delete_mstsc_history_cleared",
]


@pytest.mark.parametrize("stem", RULES_NAMING_THE_REGISTRY_OPERATION)
def test_a_registry_delete_rule_that_names_the_operation_ignores_the_other_one(stem: str) -> None:
    rule = rule_named(stem)
    fields = firing_fields(rule)
    other = {"reg-value-deleted": "reg-key-deleted", "reg-key-deleted": "reg-value-deleted"}

    wrong_operation = build_event(rule, {**fields, "event.action": other[fields["event.action"]]})

    assert not fires(rule, wrong_operation)


@pytest.mark.parametrize("stem", rule_ids())
@pytest.mark.parametrize("change", [str.upper, str.lower])
def test_a_shipped_rule_ignores_the_case_of_the_event(stem: str, change: Any) -> None:
    rule = rule_named(stem)
    fields = {
        name: change(value) if isinstance(value, str) else value
        for name, value in firing_fields(rule).items()
    }

    assert fires(rule, build_event(rule, fields))
