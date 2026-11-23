"""TPKT and X.224 as RDP uses them to negotiate the security protocol (MS-RDPBCGR 2.2.1.1, 2.2.1.2).

The Connection Request is the first thing a stranger sends to port 3389, so it is parsed strictly
and every size is bounded before bytes are read or kept.
"""

import struct
from dataclasses import dataclass

from lan_sim.services.rdp_format import RdpFormatError, ReadExactly

TPKT_VERSION = 3
TPKT_HEADER_BYTES = 4
MAX_LENGTH_INDICATOR = 255
MAX_TPKT_BYTES = TPKT_HEADER_BYTES + 1 + MAX_LENGTH_INDICATOR
X224_FIXED_BYTES = 7
MIN_TPKT_BYTES = TPKT_HEADER_BYTES + X224_FIXED_BYTES
MAX_COOKIE_BYTES = 128
CONNECTION_REQUEST_CODE = 0xE0
CONNECTION_CONFIRM_CODE = 0xD0
CONFIRM_SOURCE_REFERENCE = 0x1234

PROTOCOL_RDP = 0
PROTOCOL_SSL = 0x01
PROTOCOL_HYBRID = 0x02
PROTOCOL_HYBRID_EX = 0x08

FAILURE_SSL_REQUIRED_BY_SERVER = 0x01
FAILURE_HYBRID_REQUIRED_BY_SERVER = 0x05

NEG_REQ = 0x01
NEG_RSP = 0x02
NEG_FAILURE = 0x03
NEG_BLOCK = struct.Struct("<BBHI")
NEG_BLOCK_BYTES = NEG_BLOCK.size
COOKIE_PREFIX = b"Cookie:"
MSTSHASH_PREFIX = b"mstshash="
LINE_END = b"\r\n"
PROTOCOL_NAMES = (
    (PROTOCOL_SSL, "SSL"),
    (PROTOCOL_HYBRID, "HYBRID"),
    (PROTOCOL_HYBRID_EX, "HYBRID_EX"),
)


@dataclass(frozen=True)
class ConnectionRequest:
    """`cookie` is the username after `mstshash=`, or the whole routing cookie; None if absent."""

    cookie: str | None
    requested_protocols: int

    @property
    def requests_hybrid(self) -> bool:
        return bool(self.requested_protocols & PROTOCOL_HYBRID)


async def read_tpkt(read_exactly: ReadExactly) -> bytes:
    """The body of the next TPKT packet; the length is checked before the body is read."""
    header = await read_exactly(TPKT_HEADER_BYTES)
    version, _, length = struct.unpack(">BBH", header)
    if version != TPKT_VERSION:
        raise RdpFormatError("not a TPKT packet")
    if not MIN_TPKT_BYTES <= length <= MAX_TPKT_BYTES:
        raise RdpFormatError("the TPKT length is outside what a connection request needs")
    return await read_exactly(length - TPKT_HEADER_BYTES)


def parse_connection_request(body: bytes) -> ConnectionRequest:
    """The X.224 Connection Request in a TPKT body; `RdpFormatError` for anything malformed."""
    if len(body) < X224_FIXED_BYTES:
        raise RdpFormatError("the X.224 header is cut short")
    if body[0] != len(body) - 1:
        raise RdpFormatError("the X.224 length indicator does not match the packet")
    if body[1] & 0xF0 != CONNECTION_REQUEST_CODE:
        raise RdpFormatError("not an X.224 connection request")
    cookie, rest = _split_cookie(body[X224_FIXED_BYTES:])
    return ConnectionRequest(cookie=cookie, requested_protocols=_requested_protocols(rest))


def connection_confirm(selected_protocol: int) -> bytes:
    return _confirm(NEG_BLOCK.pack(NEG_RSP, 0, NEG_BLOCK_BYTES, selected_protocol))


def connection_failure(failure_code: int) -> bytes:
    return _confirm(NEG_BLOCK.pack(NEG_FAILURE, 0, NEG_BLOCK_BYTES, failure_code))


def describe_protocols(requested: int) -> str:
    names = [name for flag, name in PROTOCOL_NAMES if requested & flag]
    unknown = requested & ~sum(flag for flag, _ in PROTOCOL_NAMES)
    if not names and not unknown:
        return "RDP"
    return "|".join([*names, f"{unknown:#x}"] if unknown and names else names or [f"{unknown:#x}"])


def _confirm(negotiation: bytes) -> bytes:
    x224 = struct.pack(
        ">BBHHB",
        X224_FIXED_BYTES - 1 + len(negotiation),
        CONNECTION_CONFIRM_CODE,
        0,
        CONFIRM_SOURCE_REFERENCE,
        0,
    )
    return (
        struct.pack(">BBH", TPKT_VERSION, 0, TPKT_HEADER_BYTES + len(x224) + len(negotiation))
        + x224
        + negotiation
    )


def _split_cookie(variable: bytes) -> tuple[str | None, bytes]:
    """The cookie or routing token line, if any, and what follows it."""
    if not variable or variable[:1] == bytes([NEG_REQ]):
        return None, variable
    line, separator, rest = variable.partition(LINE_END)
    if not separator:
        raise RdpFormatError("the cookie line is not terminated")
    if not line.startswith(COOKIE_PREFIX):
        return None, rest
    value = line[len(COOKIE_PREFIX) :].strip()
    return _decode(value.removeprefix(MSTSHASH_PREFIX)), rest


def _decode(raw: bytes) -> str:
    return raw[:MAX_COOKIE_BYTES].decode("utf-8", errors="replace")


def _requested_protocols(rest: bytes) -> int:
    if rest[:1] != bytes([NEG_REQ]):
        return PROTOCOL_RDP
    if len(rest) < NEG_BLOCK_BYTES:
        raise RdpFormatError("the RDP_NEG_REQ is cut short")
    _, _, length, requested = NEG_BLOCK.unpack_from(rest)
    if length != NEG_BLOCK_BYTES:
        raise RdpFormatError("the RDP_NEG_REQ has the wrong length")
    return int(requested)
