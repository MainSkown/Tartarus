import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from app.rules.categories import ACTION_CATEGORIES, SUPPORTED_CATEGORIES, category_of
from app.rules.matcher import RuleMatcher
from app.rules.predicate import Event
from app.rules.rule import Rule, Validity


def fake_rule(
    rule_id: str,
    category: str,
    predicate: Callable[[Event], bool] | None,
    validity: Validity = Validity.VALID,
) -> Rule:
    return Rule(
        id=rule_id,
        title=rule_id,
        description=None,
        level="high",
        status="test",
        tags=(),
        logsource_category=category,
        path=Path(f"{rule_id}.yml"),
        content_sha256="0" * 64,
        validity=validity,
        predicate=predicate,
    )


def event_with_action(action: object) -> dict[str, Any]:
    return {"event": {"action": action}, "process": {"name": "cmd.exe"}}


def always(_: Event) -> bool:
    return True


def never(_: Event) -> bool:
    return False


@pytest.mark.parametrize(
    ("action", "category"),
    [
        ("process-created", "process_creation"),
        ("file-created", "file_event"),
        ("reg-value-set", "registry_set"),
        ("reg-key-created", "registry_add"),
        ("reg-value-deleted", "registry_delete"),
        ("reg-key-deleted", "registry_delete"),
        ("network-connection", "network_connection"),
        ("dns-query", "dns_query"),
        ("create-remote-thread", "create_remote_thread"),
        ("inject-thread", "create_remote_thread"),
    ],
)
def test_an_action_belongs_to_its_sigma_category(action: str, category: str) -> None:
    assert category_of(action) == category


@pytest.mark.parametrize(
    "action",
    [
        "api-call",
        "process-terminated",
        "file-written",
        "file-deleted",
        "http-request",
        "image-loaded",
        "process-access",
        "inject-write-memory",
        "inject-map-section",
        "inject-apc",
        "signature-matched",
        "rule-matched",
        "",
        None,
        7,
    ],
)
def test_an_action_with_no_sigma_category_has_none(action: object) -> None:
    assert category_of(action) is None


def test_the_action_table_only_names_supported_categories() -> None:
    assert set(ACTION_CATEGORIES.values()) <= SUPPORTED_CATEGORIES


def test_an_event_is_tested_only_against_the_rules_of_its_category() -> None:
    seen: list[str] = []

    def spy(name: str) -> Callable[[Event], bool]:
        def predicate(_: Event) -> bool:
            seen.append(name)
            return True

        return predicate

    matcher = RuleMatcher(
        [
            fake_rule("proc", "process_creation", spy("proc")),
            fake_rule("file", "file_event", spy("file")),
            fake_rule("dns", "dns_query", spy("dns")),
        ]
    )

    matches = matcher.match(event_with_action("file-created"))

    assert [rule.id for rule in matches] == ["file"]
    assert seen == ["file"]


def test_matching_rules_come_back_in_the_order_they_were_given() -> None:
    rules = [fake_rule(name, "process_creation", always) for name in ("c", "a", "b")]

    matches = RuleMatcher(rules).match(event_with_action("process-created"))

    assert [rule.id for rule in matches] == ["c", "a", "b"]


def test_only_the_rules_whose_predicate_holds_match() -> None:
    matcher = RuleMatcher(
        [
            fake_rule("yes", "process_creation", always),
            fake_rule("no", "process_creation", never),
        ]
    )

    assert [r.id for r in matcher.match(event_with_action("process-created"))] == ["yes"]


@pytest.mark.parametrize("validity", [Validity.INVALID, Validity.UNSUPPORTED])
def test_a_rule_that_is_not_valid_never_matches(validity: Validity) -> None:
    matcher = RuleMatcher([fake_rule("bad", "process_creation", always, validity)])

    assert matcher.match(event_with_action("process-created")) == []


def test_a_valid_rule_without_a_predicate_never_matches() -> None:
    assert (
        RuleMatcher([fake_rule("none", "process_creation", None)]).match(
            event_with_action("process-created")
        )
        == []
    )


@pytest.mark.parametrize(
    "document",
    [{}, {"event": None}, {"event": "text"}, {"event": {}}, {"event": {"action": "api-call"}}],
)
def test_an_event_without_a_category_matches_nothing(document: dict[str, Any]) -> None:
    assert RuleMatcher([fake_rule("r", "process_creation", always)]).match(document) == []


def test_a_rule_that_raises_is_disabled_and_the_others_still_match(
    caplog: pytest.LogCaptureFixture,
) -> None:
    calls = 0

    def explodes(_: Event) -> bool:
        nonlocal calls
        calls += 1
        raise RuntimeError("boom")

    matcher = RuleMatcher(
        [
            fake_rule("before", "process_creation", always),
            fake_rule("bad", "process_creation", explodes),
            fake_rule("after", "process_creation", always),
        ]
    )

    with caplog.at_level(logging.ERROR):
        first = matcher.match(event_with_action("process-created"))
        second = matcher.match(event_with_action("process-created"))
        third = matcher.match(event_with_action("process-created"))

    assert [r.id for r in first] == ["before", "after"]
    assert [r.id for r in second] == ["before", "after"]
    assert [r.id for r in third] == ["before", "after"]
    assert calls == 1
    assert matcher.disabled_rule_ids == frozenset({"bad"})
    errors = [record for record in caplog.records if record.levelno == logging.ERROR]
    assert len(errors) == 1
    assert "bad" in errors[0].getMessage()
    assert "boom" in errors[0].getMessage()


def test_a_disabled_rule_stays_disabled_for_events_of_any_category() -> None:
    def explodes(_: Event) -> bool:
        raise ValueError

    matcher = RuleMatcher([fake_rule("bad", "file_event", explodes)])
    matcher.match(event_with_action("file-created"))

    assert matcher.disabled_rule_ids == frozenset({"bad"})
    assert matcher.match(event_with_action("file-created")) == []
