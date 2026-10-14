r"""Query text to a typed AST.

Tokenisation rules, which grammar.lark encodes:
- `AND`, `OR` and `NOT` are keywords in any letter case wherever a term can start, so a free-text
  search for the word "or" is written `"or"`. After `field:` they are plain values; inside a value
  group only `OR` is a keyword.
- A word directly followed by `:` or a comparison operator is a field name, so text that contains
  a colon (`http://x`, `C:\dir`) is quoted to search for it. After `field:` a value may contain
  colons, dashes, dots, slashes, `*`, `?` and so on freely.
- Bare words and quoted strings share one backslash rule: a doubled backslash is one backslash,
  a backslash and a quote is a quote, and any other backslash stays as it is. So
  `C:\Windows\*`, `C:\\Windows\\*` and `"C:\\Windows\\*"` mean the same path (the spec's
  doubled form works, the single form works), and a UNC path needs four leading backslashes.
  A quoted string ends at its first unescaped quote, so it cannot end in a single backslash.
- `*` and `?` are wildcards in bare and quoted values alike and cannot be escaped; a bare `*`
  after `field:` is the exists test.
- Whitespace separates tokens and is otherwise ignored. A free-text word cannot start with `<`
  or `>`.
"""

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from lark import Lark, Token, Transformer, v_args
from lark.exceptions import UnexpectedCharacters, UnexpectedToken

from app.query.ast import (
    NODE_TYPES,
    And,
    Comparison,
    Exists,
    Field,
    FreeText,
    Node,
    Not,
    Or,
    Span,
    Value,
)
from app.query.errors import QueryError, QuerySyntaxError

_ESCAPE = re.compile(r'\\([\\"])')
_KEYWORDS = {"AND", "OR", "NOT"}


def _span(token: Token) -> Span:
    start = token.start_pos or 0
    return Span(start, token.end_pos or start)


def _unescape(raw: str) -> str:
    return _ESCAPE.sub(r"\1", raw)


def _value(token: Token) -> Value:
    raw = str(token)
    if token.type == "QUOTED":
        raw = raw[1:-1]
    return Value(_unescape(raw), _span(token))


def _joined(first: Span, last: Span) -> Span:
    return Span(first.start, last.end)


def _terms(children: list[Any]) -> list[Node]:
    return [child for child in children if isinstance(child, NODE_TYPES)]


@dataclass(frozen=True, slots=True)
class _Values:
    values: tuple[Value, ...]
    span: Span


@v_args(inline=False)
class _AstBuilder(Transformer[Token, Node]):
    def or_expr(self, children: list[Any]) -> Node:
        terms = _terms(children)
        if len(terms) == 1:
            return terms[0]
        return Or(tuple(terms), _joined(terms[0].span, terms[-1].span))

    def and_expr(self, children: list[Any]) -> Node:
        terms = _terms(children)
        if len(terms) == 1:
            return terms[0]
        return And(tuple(terms), _joined(terms[0].span, terms[-1].span))

    def not_expr(self, children: list[Any]) -> Node:
        if len(children) == 1:
            return cast(Node, children[0])
        keyword, term = children
        return Not(term, _joined(_span(keyword), term.span))

    def primary(self, children: list[Any]) -> Node:
        return cast(Node, children[0] if len(children) == 1 else children[1])

    def exists(self, children: list[Token]) -> Node:
        field_token, _, star = children
        field = Field(str(field_token), _span(field_token))
        return Exists(field, _joined(field.span, _span(star)))

    def comparison(self, children: list[Any]) -> Node:
        field_token, operator, operand = children
        field = Field(str(field_token), _span(field_token))
        values = operand.values if isinstance(operand, _Values) else (operand,)
        return Comparison(field, str(operator), values, _joined(field.span, operand.span))

    def value_group(self, children: list[Any]) -> _Values:
        values = tuple(child for child in children if isinstance(child, Value))
        if len(children) == 1:
            return _Values(values, values[0].span)
        return _Values(values, _joined(_span(children[0]), _span(children[-1])))

    def value(self, children: list[Token]) -> Value:
        return _value(children[0])

    alternative = value

    def free_text(self, children: list[Token]) -> Node:
        value = _value(children[0])
        return FreeText(value, value.span)


_GRAMMAR = Path(__file__).with_name("grammar.lark").read_text()
_PARSER = Lark(
    _GRAMMAR, parser="lalr", lexer="contextual", transformer=_AstBuilder(), maybe_placeholders=False
)
_STRAY_OPERATOR = re.compile(r"[<>]=?")


def parse(text: str) -> Node:
    """Parses a non-empty query; raises QuerySyntaxError, whose error carries the span."""
    try:
        return cast(Node, _PARSER.parse(text))
    except UnexpectedCharacters as error:
        raise QuerySyntaxError(_unlexable(error, text)) from None
    except UnexpectedToken as error:
        raise QuerySyntaxError(_unexpected(error, text)) from None


def _unlexable(error: UnexpectedCharacters, text: str) -> QueryError:
    start = int(error.pos_in_stream or 0)
    if text[start] == '"':
        return QueryError(start, len(text), "unterminated quoted string")
    return QueryError(start, start + 1, f"unexpected character {text[start]!r}")


def _unexpected(error: UnexpectedToken, text: str) -> QueryError:
    context = _ErrorContext(error, text)
    rules = (
        context.stray_operator,
        context.unclosed_parenthesis,
        context.missing_value,
        context.missing_term_after_keyword,
        context.stray_closing_parenthesis,
        context.bad_alternative,
        context.keyword_without_left_term,
        context.ends_too_early,
    )
    for rule in rules:
        if (found := rule()) is not None:
            return found
    return QueryError(context.start, context.end, f"unexpected {context.found}")


class _ErrorContext:
    def __init__(self, error: UnexpectedToken, text: str) -> None:
        self.token: Token = error.token
        self.expected: set[str] = set(error.expected)
        self.text = text
        self.stack: list[Any] = list(error.interactive_parser.parser_state.value_stack)
        self.at_end = self.token.type == "$END"
        self.start, self.end = _span(self.token)

    @property
    def found(self) -> str:
        return f"{str(self.token)!r}"

    def _tokens(self, kind: str) -> list[Token]:
        return [item for item in self.stack if isinstance(item, Token) and item.type == kind]

    def stray_operator(self) -> QueryError | None:
        operator = _STRAY_OPERATOR.match(str(self.token))
        if operator is None or "FIELD" not in self.expected:
            return None
        end = self.start + len(operator.group())
        return QueryError(self.start, end, f"'{operator.group()}' needs a field name before it")

    def unclosed_parenthesis(self) -> QueryError | None:
        if not (self.at_end and "RPAR" in self.expected):
            return None
        start, end = _span(self._tokens("LPAR")[-1])
        return QueryError(start, end, "unbalanced parenthesis: '(' is never closed")

    def missing_value(self) -> QueryError | None:
        if "VALUE" not in self.expected:
            return None
        field, operator = self.stack[-2:]
        start, end = _joined(_span(field), _span(operator))
        return QueryError(start, end, f"expected a value after '{self.text[start:end]}'")

    def missing_term_after_keyword(self) -> QueryError | None:
        last = self.stack[-1] if self.stack else None
        if not (self.at_end and isinstance(last, Token) and last.type in _KEYWORDS):
            return None
        start, end = _span(last)
        return QueryError(start, end, f"{last.type} needs a term after it")

    def stray_closing_parenthesis(self) -> QueryError | None:
        if self.token.type != "RPAR" or "GVALUE" in self.expected:
            return None
        if not self._tokens("LPAR"):
            message = "unbalanced parenthesis: ')' has no matching '('"
        else:
            message = "expected a term, found ')'"
        return QueryError(self.start, self.end, message)

    def bad_alternative(self) -> QueryError | None:
        if "GVALUE" in self.expected:
            return QueryError(self.start, self.end, f"expected a value, found {self.found}")
        if {"OR", "RPAR"} <= self.expected:
            return QueryError(self.start, self.end, f"expected OR or ')', found {self.found}")
        return None

    def keyword_without_left_term(self) -> QueryError | None:
        if self.token.type not in _KEYWORDS:
            return None
        return QueryError(self.start, self.end, f"{self.token.type} needs a term before it")

    def ends_too_early(self) -> QueryError | None:
        if not self.at_end:
            return None
        return QueryError(self.start, self.end, "the query ends where a term is expected")
