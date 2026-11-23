"""TDS on the wire: packet framing, the prelogin exchange and the Login7 record.

Everything here parses bytes a hostile client chose. Every length and offset is checked against
the bytes actually received before it is used, and any violation is a `TdsFormatError`, which the
service answers by ending the connection. The layouts are MS-TDS 2.2.6.4 (framing), 2.2.6.5
(prelogin) and 2.2.6.4 Login7; nothing is ever executed or evaluated.
"""

import struct
from dataclasses import dataclass

from lan_sim.ntlm import MAX_SPNEGO_BYTES
from lan_sim.service import Connection

HEADER = struct.Struct(">BBHHBB")
HEADER_BYTES = HEADER.size
END_OF_MESSAGE = 0x01
# The reply tells the client 4096 (ENVCHANGE); a client that ignores that still gets served.
NEGOTIATED_PACKET_BYTES = 4096
MAX_PACKET_BYTES = 32767
MAX_MESSAGE_BYTES = 64 * 1024
SERVER_PROCESS_ID = 52

SQL_BATCH = 0x01
RPC_REQUEST = 0x03
TABULAR_RESPONSE = 0x04
ATTENTION = 0x06
LOGIN7 = 0x10
SSPI_MESSAGE = 0x11
PRELOGIN = 0x12
REQUEST_TYPES = frozenset({SQL_BATCH, RPC_REQUEST, ATTENTION, LOGIN7, SSPI_MESSAGE, PRELOGIN})

# SQL Server 2019 RTM: 15.0.2000.5.
SERVER_VERSION = (15, 0, 2000, 5)
PRELOGIN_VERSION = 0
PRELOGIN_ENCRYPTION = 1
PRELOGIN_INSTANCE = 2
PRELOGIN_MARS = 4
PRELOGIN_TERMINATOR = 0xFF
ENCRYPT_NOT_SUPPORTED = 0x02
PRELOGIN_OPTION_BYTES = 5
MAX_PRELOGIN_OPTIONS = 16

LOGIN7_FIXED = struct.Struct("<6I4B2I")
LOGIN7_FIELD_TABLE = struct.Struct("<18H")
LOGIN7_TABLE_OFFSET = LOGIN7_FIXED.size
LOGIN7_CLIENT_ID_BYTES = 6
LOGIN7_SSPI = struct.Struct("<HH")
LOGIN7_SSPI_OFFSET = LOGIN7_TABLE_OFFSET + LOGIN7_FIELD_TABLE.size + LOGIN7_CLIENT_ID_BYTES
LOGIN7_ATTACH_FILE = struct.Struct("<HH")
LOGIN7_MINIMUM_BYTES = LOGIN7_SSPI_OFFSET + LOGIN7_SSPI.size + LOGIN7_ATTACH_FILE.size
LOGIN7_LONG_SSPI_OFFSET = LOGIN7_MINIMUM_BYTES + 4
LOGIN7_LONG_SSPI_MARKER = 0xFFFF
INTEGRATED_SECURITY = 0x80
MAX_FIELD_CHARACTERS = 128
PASSWORD_XOR = 0xA5

FIRST_TDS_72 = 0x72
FIRST_TDS_VERSION = 0x70
LAST_TDS_VERSION = 0x74
ACKNOWLEDGED_VERSION = {
    0x70: 0x70000000,
    0x71: 0x71000001,
    0x72: 0x72090002,
    0x73: 0x730B0003,
    0x74: 0x74000004,
}

ALL_HEADERS_MINIMUM_BYTES = 4


class TdsFormatError(ValueError):
    """The bytes are not TDS this server accepts; the message is ours, never the client's text."""


@dataclass(frozen=True)
class Message:
    type: int
    payload: bytes


@dataclass(frozen=True)
class TdsVersion:
    """The protocol version a client announced in Login7, which decides the reply's layout."""

    login_value: int

    @property
    def legacy_layout(self) -> bool:
        """Below TDS 7.2: UserType 2 bytes, DONE row count 4 bytes, error line number 2 bytes."""
        return self.login_value >> 24 < FIRST_TDS_72

    @property
    def acknowledged(self) -> int:
        return ACKNOWLEDGED_VERSION[self.login_value >> 24]


@dataclass(frozen=True)
class Login7Request:
    version: TdsVersion
    host: str
    user: str
    password: str
    app: str
    server: str
    language: str
    database: str
    integrated_security: bool
    sspi: bytes


def parse_header(raw: bytes) -> tuple[int, int, int]:
    """(type, status, payload length) of a packet header."""
    packet_type, status, length, _, _, _ = HEADER.unpack(raw)
    if packet_type not in REQUEST_TYPES:
        raise TdsFormatError("an unknown packet type")
    if not HEADER_BYTES <= length <= MAX_PACKET_BYTES:
        raise TdsFormatError("a packet length outside the protocol's range")
    return packet_type, status, length - HEADER_BYTES


async def read_message(connection: Connection) -> Message:
    """One request message: packets are read and joined up to the one with the EOM bit."""
    message_type: int | None = None
    payload = bytearray()
    while True:
        packet_type, status, length = parse_header(await connection.read_exactly(HEADER_BYTES))
        if message_type not in (None, packet_type):
            raise TdsFormatError("the packets of one message change type")
        message_type = packet_type
        if len(payload) + length > MAX_MESSAGE_BYTES:
            raise TdsFormatError("a message over the size cap")
        if length:
            payload += await connection.read_exactly(length)
        if status & END_OF_MESSAGE:
            return Message(message_type, bytes(payload))


def frame_message(message_type: int, data: bytes) -> bytes:
    """`data` as packets of at most the negotiated size, the last one marked end of message."""
    room = NEGOTIATED_PACKET_BYTES - HEADER_BYTES
    chunks = [data[start : start + room] for start in range(0, len(data), room)] or [b""]
    packets = []
    for index, chunk in enumerate(chunks):
        status = END_OF_MESSAGE if index == len(chunks) - 1 else 0
        header = HEADER.pack(
            message_type,
            status,
            HEADER_BYTES + len(chunk),
            SERVER_PROCESS_ID,
            (index + 1) % 256,
            0,
        )
        packets.append(header + chunk)
    return b"".join(packets)


def check_prelogin(payload: bytes) -> None:
    """Walks the option table so a malformed prelogin ends the connection; nothing is kept."""
    position = 0
    for _ in range(MAX_PRELOGIN_OPTIONS + 1):
        if position >= len(payload):
            raise TdsFormatError("the prelogin options have no terminator")
        if payload[position] == PRELOGIN_TERMINATOR:
            return
        if position + PRELOGIN_OPTION_BYTES > len(payload):
            raise TdsFormatError("a prelogin option is cut short")
        _, offset, length = struct.unpack_from(">BHH", payload, position)
        if offset + length > len(payload):
            raise TdsFormatError("a prelogin option points outside the message")
        position += PRELOGIN_OPTION_BYTES
    raise TdsFormatError("too many prelogin options")


def prelogin_response() -> bytes:
    """SQL Server 2019, no encryption, default instance, MARS off.

    Exactly four options, MARS last: impacket parses the reply with a fixed four-option layout, a
    fifth option (an empty THREADID, which servers send) shifts its fields and it reads the
    encryption byte wrong. FreeTDS, nmap and .NET take this reply as it is.
    """
    options = [
        (PRELOGIN_VERSION, struct.pack(">BBHH", *SERVER_VERSION)),
        (PRELOGIN_ENCRYPTION, bytes([ENCRYPT_NOT_SUPPORTED])),
        (PRELOGIN_INSTANCE, b"\x00"),
        (PRELOGIN_MARS, b"\x00"),
    ]
    table_bytes = PRELOGIN_OPTION_BYTES * len(options) + 1
    table, values = b"", b""
    for token, value in options:
        table += struct.pack(">BHH", token, table_bytes + len(values), len(value))
        values += value
    return table + bytes([PRELOGIN_TERMINATOR]) + values


def parse_login7(payload: bytes) -> Login7Request:
    """The fields of a Login7 record; the password is de-obfuscated, nothing is trusted."""
    if len(payload) < LOGIN7_MINIMUM_BYTES:
        raise TdsFormatError("the Login7 record is cut short")
    fixed = LOGIN7_FIXED.unpack_from(payload)
    version = _tds_version(fixed[1])
    option_flags_2 = fixed[7]
    table = LOGIN7_FIELD_TABLE.unpack_from(payload, LOGIN7_TABLE_OFFSET)
    pairs = list(zip(table[0::2], table[1::2], strict=True))
    host, user, password, app, server, _, _, language, database = pairs
    return Login7Request(
        version=version,
        host=_text(payload, *host),
        user=_text(payload, *user),
        password=_deobfuscated_text(payload, *password),
        app=_text(payload, *app),
        server=_text(payload, *server),
        language=_text(payload, *language),
        database=_text(payload, *database),
        integrated_security=bool(option_flags_2 & INTEGRATED_SECURITY),
        sspi=_sspi(payload),
    )


def strip_all_headers(payload: bytes) -> bytes:
    """The request body after the optional ALL_HEADERS block (7.2+ clients send it).

    A real block starts with its own total length, a 4-byte value that a UTF-16 text or a
    procedure name can only imitate by starting with a NUL character.
    """
    if len(payload) < ALL_HEADERS_MINIMUM_BYTES:
        return payload
    (total,) = struct.unpack_from("<I", payload)
    if ALL_HEADERS_MINIMUM_BYTES <= total <= len(payload):
        return payload[total:]
    return payload


def _tds_version(login_value: int) -> TdsVersion:
    if not FIRST_TDS_VERSION <= login_value >> 24 <= LAST_TDS_VERSION:
        raise TdsFormatError("a TDS version this server does not speak")
    return TdsVersion(login_value)


def _field_bytes(payload: bytes, offset: int, characters: int) -> bytes:
    if characters == 0:
        return b""
    if characters > MAX_FIELD_CHARACTERS:
        raise TdsFormatError("a Login7 field longer than the protocol allows")
    end = offset + 2 * characters
    if offset < LOGIN7_MINIMUM_BYTES or end > len(payload):
        raise TdsFormatError("a Login7 field points outside the record")
    return payload[offset:end]


def _text(payload: bytes, offset: int, characters: int) -> str:
    return _field_bytes(payload, offset, characters).decode("utf-16le", errors="replace")


def _deobfuscated_text(payload: bytes, offset: int, characters: int) -> str:
    raw = _field_bytes(payload, offset, characters)
    return bytes(_deobfuscated(byte) for byte in raw).decode("utf-16le", errors="replace")


def _deobfuscated(byte: int) -> int:
    unmasked = byte ^ PASSWORD_XOR
    return ((unmasked & 0x0F) << 4) | (unmasked >> 4)


def _sspi(payload: bytes) -> bytes:
    offset, length = LOGIN7_SSPI.unpack_from(payload, LOGIN7_SSPI_OFFSET)
    if length == LOGIN7_LONG_SSPI_MARKER and len(payload) >= LOGIN7_LONG_SSPI_OFFSET + 4:
        (length,) = struct.unpack_from("<I", payload, LOGIN7_LONG_SSPI_OFFSET)
    if length == 0:
        return b""
    if length > MAX_SPNEGO_BYTES:
        raise TdsFormatError("an SSPI blob over the size cap")
    if offset < LOGIN7_MINIMUM_BYTES or offset + length > len(payload):
        raise TdsFormatError("the SSPI blob points outside the record")
    return payload[offset : offset + length]
