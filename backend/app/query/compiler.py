"""Query text to an OpenSearch query: the one entry point is `compile_query`."""

from collections.abc import Callable
from dataclasses import dataclass, field
from functools import partial
from typing import Any

from app.query.ast import And, Comparison, Exists, FreeText, Node, Not, Or
from app.query.clauses import (
    ClauseError,
    any_of,
    comparison_clause,
    exists_clause,
    free_text_clause,
)
from app.query.errors import QueryError, QuerySyntaxError
from app.query.field_resolution import ResolvedField, resolve_query_field, similar_field_names
from app.query.limits import length_error, shape_errors
from app.query.parser import parse

Query = dict[str, Any]

_COLON_HINT = "put text that contains ':' in quotes to search for it"


@dataclass(frozen=True, slots=True)
class Compiled:
    """`query` is None when the text is empty (match everything) or when `errors` is not empty."""

    query: Query | None
    errors: list[QueryError] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def compile_query(text: str) -> Compiled:
    """Compiles query text; bad input comes back as errors with spans, never as an exception."""
    if not text.strip():
        return Compiled(None)
    if (too_long := length_error(text)) is not None:
        return Compiled(None, [too_long])
    try:
        root = parse(text)
    except QuerySyntaxError as error:
        return Compiled(None, [error.error])
    if limit_errors := shape_errors(root):
        return Compiled(None, limit_errors)
    builder = _Builder()
    query = builder.build(root)
    if builder.errors:
        return Compiled(None, sorted(builder.errors, key=lambda error: (error.start, error.end)))
    return Compiled(query)


def _all_of(required: list[Query], excluded: list[Query]) -> Query:
    if len(required) == 1 and not excluded:
        return required[0]
    body: Query = {}
    if required:
        body["filter"] = required
    if excluded:
        body["must_not"] = excluded
    return {"bool": body}


class _Builder:
    def __init__(self) -> None:
        self.errors: list[QueryError] = []
        self._dispatch: dict[type, Callable[[Any], Query | None]] = {
            Or: self._or,
            And: self._and,
            Not: self._not,
            Comparison: self._comparison,
            Exists: self._exists,
            FreeText: self._free_text,
        }

    def build(self, node: Node) -> Query | None:
        return self._dispatch[type(node)](node)

    def _or(self, node: Or) -> Query | None:
        clauses = self._all(node.terms)
        return None if clauses is None else any_of(clauses)

    def _and(self, node: And) -> Query | None:
        required: list[Query] = []
        excluded: list[Query] = []
        complete = True
        for term in _flattened_and(node):
            negated = isinstance(term, Not)
            clause = self.build(term.term if isinstance(term, Not) else term)
            if clause is None:
                complete = False
            else:
                (excluded if negated else required).append(clause)
        return _all_of(required, excluded) if complete else None

    def _not(self, node: Not) -> Query | None:
        clause = self.build(node.term)
        return None if clause is None else {"bool": {"must_not": [clause]}}

    def _all(self, terms: tuple[Node, ...]) -> list[Query] | None:
        clauses = [self.build(term) for term in terms]
        return None if None in clauses else [clause for clause in clauses if clause is not None]

    def _comparison(self, node: Comparison) -> Query | None:
        resolved = self._resolve(node.field.name, node.field.span.start, node.field.span.end)
        if resolved is None:
            return None
        return self._per_target(
            resolved, lambda target: comparison_clause(target, node, resolved.label)
        )

    def _exists(self, node: Exists) -> Query | None:
        resolved = self._resolve(node.field.name, node.field.span.start, node.field.span.end)
        if resolved is None:
            return None
        return self._per_target(resolved, lambda target: exists_clause(target, node.field))

    def _free_text(self, node: FreeText) -> Query | None:
        return self._attempt(lambda: free_text_clause(node.value))

    def _per_target(self, resolved: ResolvedField, make: Callable[[Any], Query]) -> Query | None:
        clauses = [self._attempt(partial(make, target)) for target in resolved.targets]
        if None in clauses:
            return None
        return any_of([clause for clause in clauses if clause is not None])

    def _attempt(self, make: Callable[[], Query]) -> Query | None:
        try:
            return make()
        except ClauseError as error:
            if error.error not in self.errors:
                self.errors.append(error.error)
            return None

    def _resolve(self, name: str, start: int, end: int) -> ResolvedField | None:
        resolved = resolve_query_field(name)
        if resolved is None:
            self.errors.append(_unknown_field(name, start, end))
        return resolved


def _flattened_and(node: And) -> list[Node]:
    terms: list[Node] = []
    for term in node.terms:
        terms.extend(_flattened_and(term) if isinstance(term, And) else [term])
    return terms


def _unknown_field(name: str, start: int, end: int) -> QueryError:
    similar = similar_field_names(name)
    if not similar:
        return QueryError(start, end, f"unknown field '{name}'; {_COLON_HINT}")
    names = ", ".join(f"'{known}'" for known in similar)
    return QueryError(start, end, f"unknown field '{name}'; did you mean {names}?", similar[0])
