"""OpenSearch clauses for one field: how each field type in the catalog is queried.

The lowercase normalizer of the index (template.py) lowercases keyword values at index time, so a
keyword is queried with the lowercased value. Flat-object values are indexed as written, so they
are matched with `case_insensitive`. A wildcard pattern gives `\\` the meaning of an escape, and
paths are full of backslashes, so a backslash is doubled before it goes into a pattern.
"""

import re
from collections.abc import Callable
from datetime import date
from ipaddress import ip_address, ip_network
from typing import Any

from app.query.ast import Comparison, Field, Span, Value
from app.query.errors import QueryError
from app.query.field_resolution import Target
from app.search.fields import TEXT_SUBFIELD, FieldType, field_by_name

Query = dict[str, Any]

FREE_TEXT_FIELDS = (
    "tartarus.summary",
    "process.command_line",
    "file.path",
    "url.full",
    "api.arguments",
)

_RANGE_BOUNDS = {">": "gt", ">=": "gte", "<": "lt", "<=": "lte"}
_NUMBERS = {FieldType.LONG, FieldType.INTEGER}
_RANGEABLE = _NUMBERS | {FieldType.DATE, FieldType.IP}
_KIND = {
    FieldType.LONG: "a number",
    FieldType.INTEGER: "a number",
    FieldType.DATE: "a date",
    FieldType.IP: "an ip",
    FieldType.BOOLEAN: "a boolean",
}
_TEXT_KIND = "a text"
_WHOLE_NUMBER = re.compile(r"[+-]?[0-9]+")
_EPOCH_MILLIS = re.compile(r"[0-9]+")
_ISO_DATE = re.compile(
    r"(?P<date>[0-9]{4}-[0-9]{2}-[0-9]{2})"
    r"(?:T(?P<hour>[0-9]{2})(?::(?P<minute>[0-9]{2})(?::(?P<second>[0-9]{2})(?:\.[0-9]{1,9})?)?)?"
    r"(?:Z|[+-][0-9]{2}(?::?[0-9]{2})?)?)?"
)
_REPEATED_STAR = re.compile(r"\*{2,}")


class ClauseError(Exception):
    def __init__(self, error: QueryError) -> None:
        super().__init__(error.message)
        self.error = error


def _fail(span: Span, message: str) -> ClauseError:
    return ClauseError(QueryError(span.start, span.end, message))


def lowercase_like_index(text: str) -> str:
    """Lowercases as Lucene's lowercase filter does: one code point to one code point.

    Python's str.lower() turns U+0130 into two code points, which would never equal the single
    one the index stored.
    """
    return "".join("i" if character == "İ" else character.lower() for character in text)


def _wildcard_pattern(text: str) -> str:
    return lowercase_like_index(text).replace("\\", "\\\\")


def _wildcard(path: str, pattern: str) -> Query:
    return {"wildcard": {path: {"value": pattern, "case_insensitive": True}}}


def _phrase(path: str, text: str) -> Query:
    return {"match_phrase": {path: text}}


def exists_clause(target: Target, field: Field) -> Query:
    _require_searchable(target, field)
    return {"exists": {"field": target.path}}


def _require_searchable(target: Target, field: Field) -> None:
    if target.definition.type is FieldType.OBJECT_DISABLED:
        raise _fail(field.span, f"{target.path} is stored but not searchable")


def comparison_clause(target: Target, comparison: Comparison, label: str) -> Query:
    """The clause for `field:value`, `field:(a OR b)` or `field > value` on one target."""
    _require_searchable(target, comparison.field)
    if comparison.op == ":":
        atoms = [atom for value in comparison.values for atom in _atoms(target, label, value)]
        return _any_value_of(atoms)
    _require_rangeable(target, comparison, label)
    (value,) = comparison.values
    bound = _RANGE_BOUNDS[comparison.op]
    return {"range": {target.path: {bound: _range_operand(target, label, value)}}}


def _require_rangeable(target: Target, comparison: Comparison, label: str) -> None:
    field_type = target.definition.type
    if field_type in _RANGEABLE:
        return
    kind = _KIND.get(field_type, _TEXT_KIND)
    raise _fail(
        comparison.span,
        f"'{comparison.op}' needs a number, date or ip field, and {label} is {kind} field",
    )


def _range_operand(target: Target, label: str, value: Value) -> Any:
    _reject_empty(value)
    _reject_wildcard(target, label, value)
    if target.definition.type is FieldType.IP:
        return _single_address(value)
    return _CONVERTERS[target.definition.type](value)


def any_of(clauses: list[Query]) -> Query:
    """A bool should over the clauses, with nested bool shoulds spliced in, or the clause itself."""
    if len(clauses) == 1:
        return clauses[0]
    alternatives: list[Query] = []
    for clause in clauses:
        alternatives.extend(_alternatives(clause))
    return {"bool": {"should": alternatives, "minimum_should_match": 1}}


def _alternatives(clause: Query) -> list[Query]:
    body = clause.get("bool")
    if body is not None and body.keys() == {"should", "minimum_should_match"}:
        return list(body["should"])
    return [clause]


def _any_value_of(atoms: list[Query]) -> Query:
    scalars = _plain_term_values(atoms) if len(atoms) > 1 else None
    if scalars is not None:
        return {"terms": {scalars[0]: scalars[1]}}
    return any_of(atoms)


def _plain_term_values(atoms: list[Query]) -> tuple[str, list[Any]] | None:
    """The field and values when every atom is a plain `term` on one field, else None."""
    paths: set[str] = set()
    values: list[Any] = []
    for atom in atoms:
        body = atom.get("term")
        if body is None:
            return None
        ((path, value),) = body.items()
        if isinstance(value, dict):
            return None
        paths.add(path)
        values.append(value)
    return (paths.pop(), values) if len(paths) == 1 else None


def _atoms(target: Target, label: str, value: Value) -> list[Query]:
    _reject_empty(value)
    field_type = target.definition.type
    if field_type in _KEYWORD_LIKE:
        return _KEYWORD_LIKE[field_type](target.path, value)
    _reject_wildcard(target, label, value)
    return [_ATOM_BUILDERS[field_type](target.path, value)]


def _reject_empty(value: Value) -> None:
    if value.text == "":
        raise _fail(value.span, "empty value")


def _reject_wildcard(target: Target, label: str, value: Value) -> None:
    field_type = target.definition.type
    if not value.has_wildcard or field_type not in _KIND:
        return
    hint = ", use a CIDR range" if field_type is FieldType.IP else ""
    raise _fail(
        value.span, f"{label} is {_KIND[field_type]} field: wildcards are not supported{hint}"
    )


def _keyword_atoms(path: str, value: Value) -> list[Query]:
    if value.has_wildcard:
        return [_wildcard(path, _wildcard_pattern(value.text))]
    return [{"term": {path: lowercase_like_index(value.text)}}]


def _keyword_with_text_atoms(path: str, value: Value) -> list[Query]:
    if value.has_wildcard:
        return [_wildcard(path, _wildcard_pattern(value.text))]
    return [
        {"term": {path: lowercase_like_index(value.text)}},
        _phrase(f"{path}.{TEXT_SUBFIELD}", value.text),
    ]


def _text_atoms(path: str, value: Value) -> list[Query]:
    if not value.has_wildcard:
        return [_phrase(path, value.text)]
    if any(character.isspace() for character in value.text):
        raise _fail(
            value.span,
            f"a wildcard on the text field {path} matches one word: remove the spaces",
        )
    return [_wildcard(path, _wildcard_pattern(value.text))]


def _flat_object_atoms(path: str, value: Value) -> list[Query]:
    if value.has_wildcard:
        return [_wildcard(path, _wildcard_pattern(value.text))]
    return [{"term": {path: {"value": lowercase_like_index(value.text), "case_insensitive": True}}}]


def _whole_number(value: Value) -> int:
    if not _WHOLE_NUMBER.fullmatch(value.text):
        raise _fail(value.span, f"'{value.text}' is not a whole number")
    return int(value.text)


def _instant(value: Value) -> str | int:
    if _EPOCH_MILLIS.fullmatch(value.text):
        return int(value.text)
    if _is_iso_8601(value.text):
        return value.text
    raise _fail(
        value.span,
        f"'{value.text}' is not a date: use ISO 8601 (2026-10-13T10:12:41Z) or epoch milliseconds",
    )


def _is_iso_8601(text: str) -> bool:
    match = _ISO_DATE.fullmatch(text)
    if match is None:
        return False
    try:
        date.fromisoformat(match["date"])
    except ValueError:
        return False
    limits = {"hour": 23, "minute": 59, "second": 59}
    return all(int(match[part] or 0) <= limit for part, limit in limits.items())


def _truth(value: Value) -> bool:
    lowered = value.text.lower()
    if lowered not in ("true", "false"):
        raise _fail(value.span, f"'{value.text}' is not true or false")
    return lowered == "true"


def _address_or_range(value: Value) -> str:
    try:
        ip_network(value.text, strict=False)
    except ValueError:
        raise _fail(value.span, f"'{value.text}' is not an IP address or CIDR range") from None
    return value.text


def _single_address(value: Value) -> str:
    try:
        ip_address(value.text)
    except ValueError:
        raise _fail(value.span, f"'{value.text}' is not an IP address") from None
    return value.text


def _term_of(convert: Callable[[Value], Any]) -> Callable[[str, Value], Query]:
    return lambda path, value: {"term": {path: convert(value)}}


def _date_atom(path: str, value: Value) -> Query:
    instant = _instant(value)
    return {"range": {path: {"gte": instant, "lte": instant}}}


_KEYWORD_LIKE: dict[FieldType, Callable[[str, Value], list[Query]]] = {
    FieldType.KEYWORD: _keyword_atoms,
    FieldType.KEYWORD_WITH_TEXT: _keyword_with_text_atoms,
    FieldType.TEXT: _text_atoms,
    FieldType.FLAT_OBJECT: _flat_object_atoms,
}
_ATOM_BUILDERS: dict[FieldType, Callable[[str, Value], Query]] = {
    FieldType.LONG: _term_of(_whole_number),
    FieldType.INTEGER: _term_of(_whole_number),
    FieldType.DATE: _date_atom,
    FieldType.BOOLEAN: _term_of(_truth),
    FieldType.IP: _term_of(_address_or_range),
}
_CONVERTERS: dict[FieldType, Callable[[Value], Any]] = {
    FieldType.LONG: _whole_number,
    FieldType.INTEGER: _whole_number,
    FieldType.DATE: _instant,
}


def free_text_clause(value: Value) -> Query:
    """Finds the text anywhere in the summary, command line, paths, URL and call arguments."""
    _reject_empty(value)
    pattern = _REPEATED_STAR.sub("*", f"*{_wildcard_pattern(value.text)}*")
    return any_of(
        [clause for name in FREE_TEXT_FIELDS for clause in _contains(name, pattern, value)]
    )


def _contains(name: str, pattern: str, value: Value) -> list[Query]:
    definition = field_by_name(name)
    clauses = [_wildcard(name, pattern)]
    if definition.type is FieldType.KEYWORD_WITH_TEXT:
        clauses.append(_phrase(f"{name}.{TEXT_SUBFIELD}", value.text))
    return clauses
