import logging
from collections import defaultdict
from collections.abc import Iterable, Mapping
from typing import Any

from app.rules.categories import category_of
from app.rules.predicate import Event
from app.rules.rule import Rule, Validity

logger = logging.getLogger(__name__)


class RuleMatcher:
    """Finds the rules an event matches; no I/O.

    Rules are indexed by logsource category, so an event is only tested against the rules of its
    own category. Only `VALID` rules with a predicate take part. A rule whose predicate raises is
    disabled for the life of this matcher, with one logged error, and the others carry on
    (decision 9 of the M4 plan).
    """

    def __init__(self, rules: Iterable[Rule]) -> None:
        by_category: defaultdict[str, list[Rule]] = defaultdict(list)
        for rule in rules:
            if rule.validity is Validity.VALID and rule.predicate and rule.logsource_category:
                by_category[rule.logsource_category].append(rule)
        self._by_category = dict(by_category)
        self._disabled: set[str] = set()

    @property
    def disabled_rule_ids(self) -> frozenset[str]:
        return frozenset(self._disabled)

    def match(self, event: Event) -> list[Rule]:
        """The rules the event matches, in the order the rules were given."""
        category = category_of(_action_of(event))
        if category is None:
            return []
        return [rule for rule in self._by_category.get(category, ()) if self._holds(rule, event)]

    def _holds(self, rule: Rule, event: Event) -> bool:
        if rule.id in self._disabled or rule.predicate is None:
            return False
        try:
            return rule.predicate(event)
        except Exception as error:  # noqa: BLE001 - decision 9: a rule must never stop the engine
            self._disabled.add(rule.id)
            logger.error("rule %s (%s) disabled after raising %r", rule.id, rule.path, error)
            return False


def _action_of(event: Event) -> Any:
    section = event.get("event")
    return section.get("action") if isinstance(section, Mapping) else None
