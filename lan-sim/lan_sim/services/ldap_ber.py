"""LDAP over BER: framing, structural checks and codec, all of it for hostile input.

The decoder of the pyasn1 `LDAPMessage` schema is recursive on the filter grammar and trusts the
lengths it reads, so a message is first read as a frame under a hard size cap and then walked
iteratively, without building anything, to bound its nesting. Only a message that passes goes to
pyasn1, and whatever pyasn1 still dislikes surfaces as `LdapProtocolError`, never as its own error.
"""

# ruff: noqa: N815 - `componentType` is the attribute name pyasn1 reads from a schema class

from typing import Any

from ldap3.protocol.rfc4511 import LDAPMessage, MessageID, ProtocolOp, SearchRequest
from pyasn1.codec.ber import decoder, encoder
from pyasn1.error import PyAsn1Error
from pyasn1.type import namedtype, univ

from lan_sim.limits import KIB
from lan_sim.service import Connection

MAX_MESSAGE_BYTES = 64 * KIB
# LDAPMessage, protocolOp and the filter's levels: real clients stay far below this.
MAX_NESTING_DEPTH = 32

SEQUENCE_TAG = 0x30
CONSTRUCTED_BIT = 0x20
HIGH_TAG_NUMBER = 0x1F
LONG_LENGTH_BIT = 0x80
MAX_LENGTH_OCTETS = 4


class LdapProtocolError(Exception):
    """The bytes are not an LDAP message this server accepts; the connection ends."""


def _replacing(types: namedtype.NamedTypes, name: str, component: Any) -> namedtype.NamedTypes:
    return namedtype.NamedTypes(
        *(
            namedtype.NamedType(name, component) if named.name == name else named
            for named in types.namedTypes
        )
    )


class ServerSearchRequest(SearchRequest):
    """ldap3's schema cannot decode a `not` filter (it is written for the client side, which only
    encodes), so the filter stays raw bytes here and `ldap_filter` reads it."""

    componentType = _replacing(SearchRequest.componentType, "filter", univ.Any())


class ServerProtocolOp(ProtocolOp):
    componentType = _replacing(ProtocolOp.componentType, "searchRequest", ServerSearchRequest())


class ServerLDAPMessage(LDAPMessage):
    componentType = _replacing(LDAPMessage.componentType, "protocolOp", ServerProtocolOp())


async def read_frame(connection: Connection) -> bytes:
    """One whole `LDAPMessage` element off the stream, header included."""
    tag = await connection.read_exactly(1)
    if tag[0] != SEQUENCE_TAG:
        raise LdapProtocolError("an LDAP message starts with a SEQUENCE")
    first_length_octet = (await connection.read_exactly(1))[0]
    length_octets = b""
    if first_length_octet & LONG_LENGTH_BIT:
        count = first_length_octet & ~LONG_LENGTH_BIT
        if not 1 <= count <= MAX_LENGTH_OCTETS:
            raise LdapProtocolError("a length of this form is not accepted")
        length_octets = await connection.read_exactly(count)
        length = int.from_bytes(length_octets, "big")
    else:
        length = first_length_octet
    header = tag + bytes([first_length_octet]) + length_octets
    if length == 0:
        raise LdapProtocolError("an empty LDAP message")
    if len(header) + length > MAX_MESSAGE_BYTES:
        raise LdapProtocolError(f"an LDAP message is at most {MAX_MESSAGE_BYTES} bytes")
    return header + await connection.read_exactly(length)


def decode_message(raw: bytes) -> Any:
    """The `LDAPMessage` in `raw`, which must be exactly one message."""
    if len(raw) > MAX_MESSAGE_BYTES:
        raise LdapProtocolError(f"an LDAP message is at most {MAX_MESSAGE_BYTES} bytes")
    _check_structure(raw)
    try:
        message, rest = decoder.decode(raw, asn1Spec=ServerLDAPMessage())
    except (PyAsn1Error, ValueError, IndexError, TypeError, AttributeError) as error:
        raise LdapProtocolError(f"not an LDAPMessage: {type(error).__name__}") from error
    if rest:
        raise LdapProtocolError("bytes after the LDAP message")
    return message


def encode_message(message_id: int, operation: str, body: Any) -> bytes:
    """The `LDAPMessage` carrying `body` as its `operation` choice (e.g. `bindResponse`)."""
    message = LDAPMessage()
    message["messageID"] = MessageID(message_id)
    message["protocolOp"][operation] = body
    return bytes(encoder.encode(message))


def _check_structure(raw: bytes) -> None:
    """Walks the TLVs once: every child inside its parent, one element in all, nesting bounded."""
    ends: list[int] = []
    position = 0
    while position < len(raw):
        while ends and position == ends[-1]:
            ends.pop()
        if not ends and position != 0:
            raise LdapProtocolError("more than one element at the top level")
        tag, content_start, content_end = read_header(raw, position, ends[-1] if ends else len(raw))
        if tag & CONSTRUCTED_BIT:
            if len(ends) + 1 >= MAX_NESTING_DEPTH:
                raise LdapProtocolError(f"nested more than {MAX_NESTING_DEPTH} levels")
            ends.append(content_end)
            position = content_start
        else:
            position = content_end
    if any(end != len(raw) for end in ends[:1]) or position != len(raw):
        raise LdapProtocolError("the message ends inside an element")


def read_header(raw: bytes, position: int, limit: int) -> tuple[int, int, int]:
    """(tag, where the content starts, where the element ends), inside `limit`."""
    if position + 2 > limit:
        raise LdapProtocolError("an element header is cut short")
    tag, length_octet = raw[position], raw[position + 1]
    if tag & HIGH_TAG_NUMBER == HIGH_TAG_NUMBER:
        raise LdapProtocolError("a high tag number is not used by LDAP")
    content_start = position + 2
    length = length_octet
    if length_octet & LONG_LENGTH_BIT:
        count = length_octet & ~LONG_LENGTH_BIT
        if not 1 <= count <= MAX_LENGTH_OCTETS:
            raise LdapProtocolError("a length of this form is not accepted")
        content_start += count
        if content_start > limit:
            raise LdapProtocolError("an element header is cut short")
        length = int.from_bytes(raw[position + 2 : content_start], "big")
    content_end = content_start + length
    if content_end > limit:
        raise LdapProtocolError("an element runs past its parent")
    return tag, content_start, content_end


def build_result(body_class: Any, code: int, diagnostic: str = "", matched_dn: bytes = b"") -> Any:
    """A response of the `LDAPResult` family (or `BindResponse`, `ExtendedResponse`)."""
    body = body_class()
    body["resultCode"] = code
    body["matchedDN"] = matched_dn
    body["diagnosticMessage"] = diagnostic
    return body
