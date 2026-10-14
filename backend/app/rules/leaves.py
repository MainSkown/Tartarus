import ipaddress
import math
import operator
from collections.abc import Callable
from typing import Any

import re2
from sigma.types import (
    CompareOperators,
    SigmaBool,
    SigmaCasedString,
    SigmaCIDRExpression,
    SigmaCompareExpression,
    SigmaExists,
    SigmaExpansion,
    SigmaFieldReference,
    SigmaNull,
    SigmaNumber,
    SigmaRegularExpression,
    SigmaString,
    SigmaTimestampPart,
    SigmaType,
    SpecialChars,
)

from app.rules.predicate import Event, Predicate, values_at
from app.rules.regexes import RegexLimits, compile_regex
from app.rules.rule import unsupported

type ValueTest = Callable[[Any], bool]

COMPARISONS = {
    CompareOperators.LT: operator.lt,
    CompareOperators.LTE: operator.le,
    CompareOperators.GT: operator.gt,
    CompareOperators.GTE: operator.ge,
    CompareOperators.NEQ: operator.ne,
}
UNSUPPORTED_VALUES: dict[type[SigmaType], str] = {
    SigmaFieldReference: "the fieldref modifier is not supported",
    SigmaTimestampPart: "timestamp part modifiers (year, month, day, ...) are not supported",
}


def compile_leaf(field: str, value: SigmaType, limits: RegexLimits) -> Predicate:
    """A predicate that is true when the event has `field` and one of its values matches `value`."""
    path = tuple(field.split("."))
    if isinstance(value, SigmaNull):
        return lambda event: not _non_null_values(event, path)
    if isinstance(value, SigmaExists):
        wanted = value.exists
        return lambda event: bool(_non_null_values(event, path)) == wanted
    test = value_test(value, limits)

    def leaf(event: Event) -> bool:
        for found in values_at(event, path):  # noqa: SIM110 - hot path, see compiler.py
            if found is not None and test(found):
                return True
        return False

    return leaf


def value_test(value: SigmaType, limits: RegexLimits) -> ValueTest:
    if isinstance(value, SigmaExpansion):
        tests = [value_test(expanded, limits) for expanded in value.values]
        return lambda found: any(test(found) for test in tests)
    builder = _BUILDERS.get(type(value))
    if builder is None:
        raise unsupported(
            UNSUPPORTED_VALUES.get(
                type(value), f"values of type {type(value).__name__} are not supported"
            )
        )
    return builder(value, limits)


def _non_null_values(event: Event, path: tuple[str, ...]) -> list[Any]:
    return [found for found in values_at(event, path) if found is not None]


def _text_of(found: Any) -> str | None:
    if isinstance(found, bool):
        return "true" if found else "false"
    if isinstance(found, str):
        return found
    return str(found) if isinstance(found, int | float) else None


def _number_of(found: Any) -> float | None:
    if isinstance(found, bool):
        return None
    if isinstance(found, int | float):
        return float(found)
    if not isinstance(found, str):
        return None
    try:
        number = float(found)
    except ValueError:
        return None
    return number if math.isfinite(number) else None


def _string_test(value: SigmaString, limits: RegexLimits) -> ValueTest:
    if value.contains_placeholder():
        raise unsupported("placeholders (the expand modifier) are not supported")
    return _text_test(
        list(value.iter_parts()), fold=not isinstance(value, SigmaCasedString), limits=limits
    )


# Sigma strings match case-insensitively, and so do Windows paths, so both sides are lowered.
# Separators are not normalised: a slash is not a backslash, exactly as in a Sigma rule.
def _text_test(parts: list[Any], *, fold: bool, limits: RegexLimits) -> ValueTest:
    literal = _literal_core(parts)
    if literal is None:
        return _wildcard_test(parts, fold, limits)
    needle, anchored_start, anchored_end = literal
    needle = needle.lower() if fold else needle
    compare = _comparison(needle, anchored_start, anchored_end)

    def test(found: Any) -> bool:
        text = _text_of(found)
        return text is not None and compare(text.lower() if fold else text)

    return test


def _literal_core(parts: list[Any]) -> tuple[str, bool, bool] | None:
    """`(text, must_start_there, must_end_there)` when the pattern is one literal, else `None`."""
    star = SpecialChars.WILDCARD_MULTI
    leading, trailing = bool(parts) and parts[0] is star, bool(parts) and parts[-1] is star
    core = parts[
        1 if leading else 0 : len(parts) - 1 if trailing and len(parts) > 1 else len(parts)
    ]
    if len(core) == 0 or (len(core) == 1 and isinstance(core[0], str)):
        return ("".join(c for c in core if isinstance(c, str)), not leading, not trailing)
    return None


def _comparison(needle: str, anchored_start: bool, anchored_end: bool) -> Callable[[str], bool]:
    if anchored_start and anchored_end:
        return lambda text: text == needle
    if anchored_start:
        return lambda text: text.startswith(needle)
    if anchored_end:
        return lambda text: text.endswith(needle)
    return lambda text: needle in text


def _wildcard_test(parts: list[Any], fold: bool, limits: RegexLimits) -> ValueTest:
    pieces = [_regex_piece(part) for part in parts]
    pattern = compile_regex(("(?is)" if fold else "(?s)") + "".join(pieces), limits)

    def test(found: Any) -> bool:
        text = _text_of(found)
        return text is not None and pattern.fullmatch(text) is not None

    return test


def _regex_piece(part: str | SpecialChars) -> str:
    if part is SpecialChars.WILDCARD_MULTI:
        return ".*"
    if part is SpecialChars.WILDCARD_SINGLE:
        return "."
    return str(re2.escape(str(part)))


def _number_test(value: SigmaNumber) -> ValueTest:
    wanted = float(value.number)

    def test(found: Any) -> bool:
        return _number_of(found) == wanted

    return test


def _bool_test(value: SigmaBool) -> ValueTest:
    wanted = "true" if value.boolean else "false"

    def test(found: Any) -> bool:
        text = _text_of(found)
        return isinstance(found, bool | str) and text is not None and text.lower() == wanted

    return test


def _compare_test(value: SigmaCompareExpression) -> ValueTest:
    compare = COMPARISONS[value.op]
    bound = float(value.number.number)

    def test(found: Any) -> bool:
        number = _number_of(found)
        return number is not None and compare(number, bound)

    return test


def _cidr_test(value: SigmaCIDRExpression) -> ValueTest:
    network = value.network

    def test(found: Any) -> bool:
        try:
            return ipaddress.ip_address(str(found)) in network
        except ValueError:
            return False

    return test


def _regex_test(value: SigmaRegularExpression, limits: RegexLimits) -> ValueTest:
    flags = "".join(sorted(SigmaRegularExpression.sigma_to_re_flag[flag] for flag in value.flags))
    prefix = f"(?{flags})" if flags else ""
    pattern = compile_regex(prefix + str(value.regexp), limits)
    cap = limits.max_input_length

    def test(found: Any) -> bool:
        text = _text_of(found)
        return text is not None and pattern.search(text[:cap]) is not None

    return test


_BUILDERS: dict[type, Callable[[Any, RegexLimits], ValueTest]] = {
    SigmaString: _string_test,
    SigmaCasedString: _string_test,
    SigmaNumber: lambda value, _: _number_test(value),
    SigmaBool: lambda value, _: _bool_test(value),
    SigmaCompareExpression: lambda value, _: _compare_test(value),
    SigmaCIDRExpression: lambda value, _: _cidr_test(value),
    SigmaRegularExpression: _regex_test,
}
