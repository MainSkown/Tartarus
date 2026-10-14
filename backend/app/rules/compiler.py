from sigma.conditions import (
    ConditionAND,
    ConditionFieldEqualsValueExpression,
    ConditionNOT,
    ConditionOR,
    ConditionValueExpression,
)
from sigma.rule import SigmaRule

from app.rules.leaves import compile_leaf
from app.rules.predicate import Event, Predicate
from app.rules.regexes import DEFAULT_LIMITS, RegexLimits
from app.rules.rule import unsupported

__all__ = ["RegexLimits", "compile_sigma_rule"]


def compile_sigma_rule(rule: SigmaRule, limits: RegexLimits = DEFAULT_LIMITS) -> Predicate:
    """A predicate over event documents that is true when the rule's condition holds.

    The rule must already be mapped to catalog fields (`app.rules.mapping.map_fields`). Raises
    `RuleProblem` for a construct the engine cannot run or a regular expression over `limits`.
    """
    conditions = [
        compile_node(parsed.parse(), limits) for parsed in rule.detection.parsed_condition
    ]
    return _any_of(conditions)


def compile_node(node: object, limits: RegexLimits) -> Predicate:
    if isinstance(node, ConditionAND):
        return _all_of([compile_node(arg, limits) for arg in node.args])
    if isinstance(node, ConditionOR):
        return _any_of([compile_node(arg, limits) for arg in node.args])
    if isinstance(node, ConditionNOT):
        negated = compile_node(node.args[0], limits)
        return lambda event: not negated(event)
    if isinstance(node, ConditionFieldEqualsValueExpression):
        return compile_leaf(node.field, node.value, limits)
    if isinstance(node, ConditionValueExpression):
        raise unsupported("keyword searches without a field are not supported")
    raise unsupported(f"condition element {type(node).__name__} is not supported")


# The loops below are the hot path of every event; a generator inside all()/any() costs about
# twice as much per call (measured by tests/rules/test_performance.py).
def _all_of(predicates: list[Predicate]) -> Predicate:
    def check(event: Event) -> bool:
        for predicate in predicates:  # noqa: SIM110
            if not predicate(event):
                return False
        return True

    return check


def _any_of(predicates: list[Predicate]) -> Predicate:
    def check(event: Event) -> bool:
        for predicate in predicates:  # noqa: SIM110
            if predicate(event):
                return True
        return False

    return check
