from collections.abc import Callable

from sigma.conditions import (
    ConditionAND,
    ConditionFieldEqualsValueExpression,
    ConditionNOT,
    ConditionOR,
)
from sigma.rule import SigmaRule

from app.rules.leaves import compile_leaf_explainer
from app.rules.predicate import Event, Explainer
from app.rules.regexes import DEFAULT_LIMITS, RegexLimits
from app.rules.rule import unsupported

type NodeExplainer = Callable[[Event], list[str] | None]


def explain_sigma_rule(rule: SigmaRule, limits: RegexLimits = DEFAULT_LIMITS) -> Explainer:
    """The `field: value` pieces of an event that make the rule's condition hold, in order.

    Only for an event the rule's predicate matched (`compile_sigma_rule`); on one it does not match
    the result is empty. The rule must already be compiled without a `RuleProblem`, so every node
    here is one the compiler accepted.
    """
    conditions = [
        _explain_node(parsed.parse(), limits) for parsed in rule.detection.parsed_condition
    ]

    def explain(event: Event) -> list[str]:
        pieces: list[str] = []
        for condition in conditions:
            pieces += condition(event) or []
        return pieces

    return explain


def _explain_node(node: object, limits: RegexLimits) -> NodeExplainer:
    if isinstance(node, ConditionAND):
        return _all_of([_explain_node(arg, limits) for arg in node.args])
    if isinstance(node, ConditionOR):
        return _any_of([_explain_node(arg, limits) for arg in node.args])
    if isinstance(node, ConditionNOT):
        return _none_of(_explain_node(node.args[0], limits))
    if isinstance(node, ConditionFieldEqualsValueExpression):
        return compile_leaf_explainer(node.field, node.value, limits)
    raise unsupported(f"condition element {type(node).__name__} is not supported")


def _all_of(explainers: list[NodeExplainer]) -> NodeExplainer:
    def explain(event: Event) -> list[str] | None:
        pieces: list[str] = []
        for explainer in explainers:
            if (found := explainer(event)) is None:
                return None
            pieces += found
        return pieces

    return explain


def _any_of(explainers: list[NodeExplainer]) -> NodeExplainer:
    def explain(event: Event) -> list[str] | None:
        held = [found for explainer in explainers if (found := explainer(event)) is not None]
        return [piece for pieces in held for piece in pieces] if held else None

    return explain


def _none_of(explainer: NodeExplainer) -> NodeExplainer:
    # A `not` holds because something is absent or different, so it contributes nothing to list.
    def explain(event: Event) -> list[str] | None:
        return [] if explainer(event) is None else None

    return explain
