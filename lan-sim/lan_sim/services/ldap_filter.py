"""A search filter, still raw BER, rendered as RFC 4515 text for the log.

Only the log needs it: this server never evaluates a filter. Reading the bytes here instead of
through ldap3's schema keeps a hostile filter out of pyasn1's recursion; the nesting is already
bounded by `ldap_ber.decode_message`, and a tag that is not a filter ends the connection.
"""

from collections.abc import Callable

from lan_sim.services.ldap_ber import LdapProtocolError, read_header

ELLIPSIS = "…"
ESCAPED = {"\\": r"\5c", "(": r"\28", ")": r"\29", "*": r"\2a"}
DELETE = 0x7F
FIRST_PRINTABLE = 0x20

AND, OR, NOT = 0xA0, 0xA1, 0xA2
EQUALITY, SUBSTRINGS, GREATER_OR_EQUAL, LESS_OR_EQUAL = 0xA3, 0xA4, 0xA5, 0xA6
PRESENT, APPROXIMATE, EXTENSIBLE = 0x87, 0xA8, 0xA9
SUBSTRING_INITIAL, SUBSTRING_ANY, SUBSTRING_FINAL = 0x80, 0x81, 0x82
MATCHING_RULE, EXTENSIBLE_TYPE, EXTENSIBLE_VALUE, DN_ATTRIBUTES = 0x81, 0x82, 0x83, 0x84

Element = tuple[int, bytes]
COMPARISONS = {EQUALITY: "=", GREATER_OR_EQUAL: ">=", LESS_OR_EQUAL: "<=", APPROXIMATE: "~="}


def render_filter(raw: bytes, max_length: int) -> str:
    """`raw` is one filter element; `LdapProtocolError` if it is not one this server understands."""
    text = _filter(*_only(_elements(raw)))
    if len(text) > max_length:
        return text[: max_length - 1] + ELLIPSIS
    return text


def _filter(tag: int, content: bytes) -> str:
    if tag in (AND, OR):
        operator = "&" if tag == AND else "|"
        return f"({operator}{''.join(_filter(*child) for child in _elements(content))})"
    if tag == NOT:
        return f"(!{_filter(*_only(_elements(content)))})"
    if tag in COMPARISONS:
        attribute, value = _attribute_and_value(content)
        return f"({attribute}{COMPARISONS[tag]}{value})"
    return _other_filter(tag, content)


def _other_filter(tag: int, content: bytes) -> str:
    renderers: dict[int, Callable[[bytes], str]] = {
        PRESENT: lambda content: f"({_escaped(content)}=*)",
        SUBSTRINGS: _substrings,
        EXTENSIBLE: _extensible,
    }
    if tag not in renderers:
        raise LdapProtocolError(f"tag {tag:#04x} is not a filter")
    return renderers[tag](content)


def _only(elements: list[Element]) -> Element:
    if len(elements) != 1:
        raise LdapProtocolError("exactly one filter was expected")
    return elements[0]


def _attribute_and_value(content: bytes) -> tuple[str, str]:
    try:
        [(_, attribute), (_, value)] = _elements(content)
    except ValueError as error:
        raise LdapProtocolError("an assertion is an attribute and a value") from error
    return _escaped(attribute), _escaped(value)


def _substrings(content: bytes) -> str:
    try:
        [(_, attribute), (_, parts)] = _elements(content)
    except ValueError as error:
        raise LdapProtocolError("a substring filter is an attribute and its parts") from error
    pieces = {SUBSTRING_INITIAL: "", SUBSTRING_ANY: "*", SUBSTRING_FINAL: "*"}
    ordered = [(tag, value) for tag, value in _elements(parts) if tag in pieces]
    text = "".join(f"{pieces[tag]}{_escaped(value)}" for tag, value in ordered)
    if not ordered or ordered[-1][0] != SUBSTRING_FINAL:
        text += "*"
    return f"({_escaped(attribute)}={text})"


def _extensible(content: bytes) -> str:
    fields = dict(_elements(content))
    attribute = _escaped(fields.get(EXTENSIBLE_TYPE, b""))
    rule = f":{_escaped(fields[MATCHING_RULE])}" if MATCHING_RULE in fields else ""
    dn = ":dn" if fields.get(DN_ATTRIBUTES, b"\x00") != b"\x00" else ""
    return f"({attribute}{dn}{rule}:={_escaped(fields.get(EXTENSIBLE_VALUE, b''))})"


def _elements(raw: bytes) -> list[Element]:
    """The TLVs laid end to end in `raw`, as (tag, content)."""
    elements: list[Element] = []
    position = 0
    while position < len(raw):
        tag, content_start, content_end = read_header(raw, position, len(raw))
        elements.append((tag, raw[content_start:content_end]))
        position = content_end
    return elements


def _escaped(raw: bytes) -> str:
    text = raw.decode("utf-8", errors="replace")
    return "".join(_escape_character(character) for character in text)


def _escape_character(character: str) -> str:
    if character in ESCAPED:
        return ESCAPED[character]
    if ord(character) < FIRST_PRINTABLE or ord(character) == DELETE:
        return f"\\{ord(character):02x}"
    return character
