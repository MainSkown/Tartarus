"""Builds an event that a rule's own selection should match, from the rule's parsed tree.

The construction works on the Sigma values (what text satisfies `*a*`, `b*`, `*c`), not on the
engine's matcher, so a test that feeds the event to the engine checks the engine against an
independent reading of the rule. A rule the helper cannot satisfy is written by hand.
"""

import itertools
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

from sigma.conditions import (
    ConditionAND,
    ConditionFieldEqualsValueExpression,
    ConditionNOT,
    ConditionOR,
)
from sigma.types import (
    CompareOperators,
    SigmaCIDRExpression,
    SigmaCompareExpression,
    SigmaExpansion,
    SigmaNumber,
    SigmaString,
    SigmaType,
    SpecialChars,
)

ALTERNATIVES_PER_OR = 3
MAX_ALTERNATIVES = 60


class CannotSatisfy(Exception):  # noqa: N818 - a signal, not an error
    pass


@dataclass
class Fragment:
    """What one leaf demands of a field: text anchored at the start, the end, both, or neither."""

    exact: str | None = None
    prefix: str = ""
    suffix: str = ""
    inside: list[str] = field(default_factory=list)
    value: object = None


Assignment = dict[str, Fragment]


def alternatives(node: object) -> Iterator[Assignment]:
    """Assignments of fields that make `node` true, the cheapest first. `not` demands nothing."""
    if isinstance(node, ConditionFieldEqualsValueExpression):
        yield from _leaf(node.field, node.value)
    elif isinstance(node, ConditionNOT):
        yield {}
    elif isinstance(node, ConditionOR):
        for child in node.args:
            yield from itertools.islice(alternatives(child), ALTERNATIVES_PER_OR)
    elif isinstance(node, ConditionAND):
        children = [list(itertools.islice(alternatives(c), ALTERNATIVES_PER_OR)) for c in node.args]
        for combination in itertools.islice(itertools.product(*children), MAX_ALTERNATIVES):
            merged = _merge_all(combination)
            if merged is not None:
                yield merged
    else:
        raise CannotSatisfy(type(node).__name__)


def negated_parts(node: object) -> Iterator[object]:
    """The subtrees under a `not`, anywhere in the tree."""
    if isinstance(node, ConditionNOT):
        yield node.args[0]
    for child in getattr(node, "args", []):
        yield from negated_parts(child)


def _leaf(field_name: str, value: SigmaType) -> Iterator[Assignment]:
    if isinstance(value, SigmaExpansion):
        for expanded in value.values[:ALTERNATIVES_PER_OR]:
            yield from _leaf(field_name, expanded)
    elif isinstance(value, SigmaString):
        yield {field_name: _string_fragment(value)}
    elif isinstance(value, SigmaNumber):
        yield {field_name: Fragment(value=value.number)}
    elif isinstance(value, SigmaCompareExpression):
        yield {field_name: Fragment(value=_beyond(value))}
    elif isinstance(value, SigmaCIDRExpression):
        yield {field_name: Fragment(value=str(next(iter(value.network.hosts()))))}
    else:
        raise CannotSatisfy(f"{field_name}: {type(value).__name__}")


def _beyond(value: SigmaCompareExpression) -> float:
    bound = value.number.number
    step = {CompareOperators.GT: 1, CompareOperators.GTE: 0}.get(value.op, -1)
    return bound + step


def _string_fragment(value: SigmaString) -> Fragment:
    parts = list(value.iter_parts())
    star = SpecialChars.WILDCARD_MULTI
    text = "".join(
        "a" if p is SpecialChars.WILDCARD_SINGLE else "" if p is star else str(p) for p in parts
    )
    leading, trailing = bool(parts) and parts[0] is star, bool(parts) and parts[-1] is star
    if any(p is star for p in parts[1:-1]) or any(p is SpecialChars.WILDCARD_SINGLE for p in parts):
        return Fragment(exact=text)
    if leading and trailing:
        return Fragment(inside=[text])
    if leading:
        return Fragment(suffix=text)
    if trailing:
        return Fragment(prefix=text)
    return Fragment(exact=text)


def _merge_all(combination: tuple[Assignment, ...]) -> Assignment | None:
    merged: Assignment = {}
    for assignment in combination:
        for name, fragment in assignment.items():
            if name not in merged:
                merged[name] = fragment
            elif (joined := _join(merged[name], fragment)) is None:
                return None
            else:
                merged[name] = joined
    return merged


def _join(left: Fragment, right: Fragment) -> Fragment | None:
    if left.value is not None or right.value is not None:
        return left if left.value == right.value else None
    if left.exact is not None and right.exact is not None:
        return left if left.exact == right.exact else None
    if left.exact is not None or right.exact is not None:
        return left if left.exact is not None else right
    return Fragment(
        prefix=left.prefix or right.prefix,
        suffix=left.suffix or right.suffix,
        inside=[*left.inside, *right.inside],
    )


def text_of(fragment: Fragment) -> object:
    if fragment.value is not None:
        return fragment.value
    if fragment.exact is not None:
        return fragment.exact
    return fragment.prefix + "".join(fragment.inside) + fragment.suffix


def event_fields(assignment: Assignment) -> dict[str, Any]:
    return {name: text_of(fragment) for name, fragment in assignment.items()}
