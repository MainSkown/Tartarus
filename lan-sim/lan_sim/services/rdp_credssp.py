"""The CredSSP TSRequest (MS-CSSP 2.2.1) as DER: read from a stream, parse strictly, build.

Only the parts the NTLM capture needs are understood. Every length is checked against the
enclosing element and against `MAX_TS_REQUEST_BYTES` before bytes are read or sliced.
"""

from dataclasses import dataclass

from lan_sim.ntlm import MAX_SPNEGO_BYTES
from lan_sim.services.rdp_format import RdpFormatError, ReadExactly

MAX_TS_REQUEST_BYTES = MAX_SPNEGO_BYTES + 4096
SERVER_VERSION = 6
MIN_VERSION = 2
STATUS_LOGON_FAILURE = 0xC000006D
MAX_LENGTH_OCTETS = 3
MAX_INTEGER_BYTES = 5
ERROR_CODE_BYTES = 4
LONG_FORM = 0x80
SHORT_FORM_LIMIT = 0x80

SEQUENCE = 0x30
INTEGER = 0x02
OCTET_STRING = 0x04
VERSION_FIELD = 0xA0
NEGO_TOKENS_FIELD = 0xA1
AUTH_INFO_FIELD = 0xA2
PUB_KEY_AUTH_FIELD = 0xA3
ERROR_CODE_FIELD = 0xA4
NEGO_TOKEN_FIELD = 0xA0


@dataclass(frozen=True)
class TsRequest:
    version: int
    nego_token: bytes | None
    error_code: int | None
    has_auth_info: bool
    has_pub_key_auth: bool


async def read_ts_request(read_exactly: ReadExactly) -> bytes:
    """The next DER SEQUENCE from the stream, header included, within `MAX_TS_REQUEST_BYTES`."""
    first, second = await read_exactly(2)
    if first != SEQUENCE:
        raise RdpFormatError("a TSRequest is a DER sequence")
    if second < SHORT_FORM_LIMIT:
        length_octets, length = b"", second
    else:
        count = second - LONG_FORM
        if not 1 <= count <= MAX_LENGTH_OCTETS:
            raise RdpFormatError("a DER length of this form is not accepted")
        length_octets = await read_exactly(count)
        length = int.from_bytes(length_octets, "big")
    if length > MAX_TS_REQUEST_BYTES:
        raise RdpFormatError("a TSRequest is larger than any CredSSP message here")
    body = await read_exactly(length) if length else b""
    return bytes([first, second]) + length_octets + body


def parse_ts_request(packet: bytes) -> TsRequest:
    """The TSRequest in `packet`; `RdpFormatError` for anything malformed or with trailing bytes."""
    tag, start, end = _element(packet, 0, len(packet))
    if tag != SEQUENCE or end != len(packet):
        raise RdpFormatError("not a single DER sequence")
    fields = _fields(packet, start, end)
    if VERSION_FIELD not in fields:
        raise RdpFormatError("the TSRequest has no version")
    nego = fields.get(NEGO_TOKENS_FIELD)
    error_code = fields.get(ERROR_CODE_FIELD)
    return TsRequest(
        version=_integer(packet, fields[VERSION_FIELD]),
        nego_token=None if nego is None else _first_nego_token(packet, nego),
        error_code=None if error_code is None else _integer(packet, error_code, signed=False),
        has_auth_info=AUTH_INFO_FIELD in fields,
        has_pub_key_auth=PUB_KEY_AUTH_FIELD in fields,
    )


def build_ts_request(
    version: int, *, nego_token: bytes | None = None, error_code: int | None = None
) -> bytes:
    body = _tlv(VERSION_FIELD, _tlv(INTEGER, bytes([version])))
    if nego_token is not None:
        entry = _tlv(SEQUENCE, _tlv(NEGO_TOKEN_FIELD, _tlv(OCTET_STRING, nego_token)))
        body += _tlv(NEGO_TOKENS_FIELD, _tlv(SEQUENCE, entry))
    if error_code is not None:
        body += _tlv(ERROR_CODE_FIELD, _tlv(INTEGER, error_code.to_bytes(ERROR_CODE_BYTES, "big")))
    return _tlv(SEQUENCE, body)


def _element(data: bytes, offset: int, limit: int) -> tuple[int, int, int]:
    """(tag, value start, value end) of the DER element at `offset`, within `limit`."""
    if offset + 2 > limit:
        raise RdpFormatError("a DER element is cut short")
    tag, first = data[offset], data[offset + 1]
    offset += 2
    length = first
    if first >= SHORT_FORM_LIMIT:
        count = first - LONG_FORM
        if not 1 <= count <= MAX_LENGTH_OCTETS or offset + count > limit:
            raise RdpFormatError("a DER length is not accepted")
        length = int.from_bytes(data[offset : offset + count], "big")
        offset += count
    if offset + length > limit:
        raise RdpFormatError("a DER element is longer than its container")
    return tag, offset, offset + length


def _fields(data: bytes, start: int, end: int) -> dict[int, tuple[int, int]]:
    """The context-tagged fields of the TSRequest, by tag, as (value start, value end)."""
    fields: dict[int, tuple[int, int]] = {}
    position = start
    while position < end:
        tag, value_start, value_end = _element(data, position, end)
        fields.setdefault(tag, (value_start, value_end))
        position = value_end
    return fields


def _expect(data: bytes, span: tuple[int, int], tag: int) -> tuple[int, int]:
    found, start, end = _element(data, span[0], span[1])
    if found != tag or end != span[1]:
        raise RdpFormatError("a DER element is not what a TSRequest has there")
    return start, end


def _integer(data: bytes, span: tuple[int, int], *, signed: bool = True) -> int:
    start, end = _expect(data, span, INTEGER)
    if not 1 <= end - start <= MAX_INTEGER_BYTES:
        raise RdpFormatError("a DER integer has an unexpected size")
    return int.from_bytes(data[start:end], "big", signed=signed)


def _first_nego_token(data: bytes, span: tuple[int, int]) -> bytes:
    """negoTokens is SEQUENCE OF SEQUENCE { negoToken [0] OCTET STRING }; the first one is used."""
    entries = _expect(data, span, SEQUENCE)
    entry = _expect(data, entries, SEQUENCE)
    wrapper = _expect(data, entry, NEGO_TOKEN_FIELD)
    start, end = _expect(data, wrapper, OCTET_STRING)
    return data[start:end]


def _tlv(tag: int, content: bytes) -> bytes:
    size = len(content)
    if size < SHORT_FORM_LIMIT:
        return bytes([tag, size]) + content
    octets = size.to_bytes((size.bit_length() + 7) // 8, "big")
    return bytes([tag, LONG_FORM + len(octets)]) + octets + content
