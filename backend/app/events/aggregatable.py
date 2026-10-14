"""Field names an aggregation may run on: resolved through the query's own resolution."""

from app.errors import ApiError
from app.query.field_resolution import ResolvedField, resolve_query_field, similar_field_names
from app.search.fields import FieldType


def resolve_for_aggregation(name: str, allowed: frozenset[FieldType], code: str) -> ResolvedField:
    """The field a name or alias stands for, or a 422 under `code` saying why it cannot be used.

    A composite alias resolves to all its members; the caller decides whether that is usable.
    """
    resolved = resolve_query_field(name)
    if resolved is None:
        raise ApiError(422, code, _unknown_message(name))
    for target in resolved.targets:
        if target.definition.type not in allowed:
            kind = target.definition.type.value.replace("_", " ")
            raise ApiError(422, code, f"{name} is a {kind} field and cannot be used here")
    return resolved


def _unknown_message(name: str) -> str:
    similar = similar_field_names(name)
    hint = f"; did you mean {', '.join(repr(known) for known in similar)}?" if similar else ""
    return f"unknown field '{name}'{hint}"
