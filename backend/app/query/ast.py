from collections.abc import Iterator
from dataclasses import dataclass
from typing import NamedTuple

WILDCARD_CHARACTERS = "*?"


class Span(NamedTuple):
    """Character offsets into the query text; `end` is exclusive."""

    start: int
    end: int


@dataclass(frozen=True, slots=True)
class Field:
    name: str
    span: Span


@dataclass(frozen=True, slots=True)
class Value:
    """A value with its quotes removed and its backslash escapes resolved."""

    text: str
    span: Span

    @property
    def has_wildcard(self) -> bool:
        return any(character in self.text for character in WILDCARD_CHARACTERS)


@dataclass(frozen=True, slots=True)
class Comparison:
    field: Field
    op: str
    values: tuple[Value, ...]
    span: Span


@dataclass(frozen=True, slots=True)
class Exists:
    field: Field
    span: Span


@dataclass(frozen=True, slots=True)
class FreeText:
    value: Value
    span: Span


@dataclass(frozen=True, slots=True)
class Not:
    term: "Node"
    span: Span


@dataclass(frozen=True, slots=True)
class And:
    terms: tuple["Node", ...]
    span: Span


@dataclass(frozen=True, slots=True)
class Or:
    terms: tuple["Node", ...]
    span: Span


Node = Or | And | Not | Comparison | Exists | FreeText
NODE_TYPES = (Or, And, Not, Comparison, Exists, FreeText)


def children_of(node: Node) -> tuple[Node, ...]:
    match node:
        case And(terms) | Or(terms):
            return terms
        case Not(term):
            return (term,)
    return ()


def walk(root: Node) -> Iterator[tuple[Node, int]]:
    """Yields every node in document order with its nesting depth, without recursion.

    The depth counts the AND, OR and NOT nodes on the path from the root, the node itself
    included; a comparison therefore sits at the depth of the operators around it.
    """
    stack: list[tuple[Node, int]] = [(root, 0)]
    while stack:
        node, depth = stack.pop()
        if isinstance(node, And | Or | Not):
            depth += 1
        yield node, depth
        stack.extend((child, depth) for child in reversed(children_of(node)))
