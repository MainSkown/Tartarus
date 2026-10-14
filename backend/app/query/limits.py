"""Caps that keep one query from costing the cluster too much (plan M3, decision 5)."""

from app.query.ast import Comparison, Exists, FreeText, Node, Span, walk
from app.query.errors import QueryError

MAX_QUERY_LENGTH = 2000
MAX_DEPTH = 20
MAX_TERMS = 100
MAX_WILDCARD_TERMS = 25


def length_error(text: str) -> QueryError | None:
    if len(text) <= MAX_QUERY_LENGTH:
        return None
    message = f"the query is {len(text)} characters long, the limit is {MAX_QUERY_LENGTH}"
    return QueryError(MAX_QUERY_LENGTH, len(text), message)


def shape_errors(root: Node) -> list[QueryError]:
    """Depth, term and wildcard caps, each reported at the first place it is exceeded."""
    found = [
        _depth_error(root),
        _count_error(_terms(root), MAX_TERMS, f"the query has more than {MAX_TERMS} terms"),
        _count_error(
            _wildcard_terms(root),
            MAX_WILDCARD_TERMS,
            f"the query has more than {MAX_WILDCARD_TERMS} wildcard terms "
            "(a free-text word counts as one)",
        ),
    ]
    return [error for error in found if error is not None]


def _depth_error(root: Node) -> QueryError | None:
    for node, depth in walk(root):
        if depth > MAX_DEPTH:
            message = f"the query nests AND, OR and NOT deeper than {MAX_DEPTH} levels"
            return QueryError(node.span.start, node.span.end, message)
    return None


def _count_error(spans: list[Span], limit: int, message: str) -> QueryError | None:
    if len(spans) <= limit:
        return None
    first_over = spans[limit]
    return QueryError(first_over.start, first_over.end, message)


def _terms(root: Node) -> list[Span]:
    return [span for node, _ in walk(root) for span, _ in _node_terms(node)]


def _wildcard_terms(root: Node) -> list[Span]:
    return [
        span for node, _ in walk(root) for span, is_wildcard in _node_terms(node) if is_wildcard
    ]


def _node_terms(node: Node) -> list[tuple[Span, bool]]:
    """The spans of what a node searches for, flagged when the search is wildcard-like.

    A free-text word is searched as "contains", which is a leading-wildcard query.
    """
    match node:
        case Comparison(_, _, values):
            return [(value.span, value.has_wildcard) for value in values]
        case Exists(_, span):
            return [(span, False)]
        case FreeText(value):
            return [(value.span, True)]
    return []
