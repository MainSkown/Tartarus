"""SMB on the wire: NetBIOS framing, the SMB2 header, compound chains and the SMB1 negotiate.

Everything here parses bytes a client chose, so every failure is an `SmbFormatError` and nothing
else: the connection ends, the daemon never sees an exception from inside a parser.
"""

import struct
from dataclasses import dataclass
from typing import Protocol

SMB2_MAGIC = b"\xfeSMB"
SMB1_MAGIC = b"\xffSMB"
HEADER_SIZE = 64
SMB2_STRUCTURE_SIZE = 64
SIGNATURE_BYTES = 16
SIGNATURE_OFFSET = 48
COMPOUND_ALIGNMENT = 8
MAX_COMPOUND_MESSAGES = 16
MAX_SMB1_DIALECTS = 32

NBSS_MESSAGE = 0x00
NBSS_KEEP_ALIVE = 0x85
NBSS_HEADER_BYTES = 4

FLAG_RESPONSE = 0x1
FLAG_ASYNC = 0x2
FLAG_RELATED = 0x4
FLAG_SIGNED = 0x8

SMB1_NEGOTIATE_COMMAND = 0x72
SMB1_HEADER_BYTES = 32
SMB1_NEGOTIATE_REPLY_FLAGS = 0x98
SMB1_NEGOTIATE_REPLY_FLAGS2 = 0xC801
SMB1_NO_COMMON_DIALECT = 0xFFFF
SMB1_DIALECT_MARKER = 0x02
SMB1_STATUS_SUCCESS = 0
SMB1_WILDCARD_DIALECT = "SMB 2.???"
SMB1_SMB2_002_DIALECT = "SMB 2.002"

_HEADER = struct.Struct("<4sHHIHHIIQIIQ16s")
_SMB1_COUNTS = struct.Struct("<BH")
_SMB1_REFUSAL = struct.Struct("<4sBIBHH8sHHHHHBHH")


class SmbFormatError(Exception):
    """The bytes are not an SMB message this server accepts."""


class _Reader(Protocol):
    async def read_exactly(self, size: int) -> bytes: ...


@dataclass(frozen=True)
class Header:
    command: int
    status: int = 0
    flags: int = 0
    next_command: int = 0
    message_id: int = 0
    tree_id: int = 0
    session_id: int = 0
    credit_charge: int = 0
    credit_request: int = 0
    signature: bytes = bytes(SIGNATURE_BYTES)


@dataclass(frozen=True)
class Smb1Negotiate:
    dialects: tuple[str, ...]
    offers_smb2_wildcard: bool
    offers_smb2_002: bool


def parse_header(data: bytes) -> Header:
    if len(data) < HEADER_SIZE:
        raise SmbFormatError("an SMB2 header is cut short")
    (
        magic,
        structure_size,
        credit_charge,
        status,
        command,
        credit_request,
        flags,
        next_command,
        message_id,
        _reserved,
        tree_id,
        session_id,
        signature,
    ) = _HEADER.unpack_from(data)
    if magic != SMB2_MAGIC or structure_size != SMB2_STRUCTURE_SIZE:
        raise SmbFormatError("not an SMB2 header")
    if flags & FLAG_ASYNC:
        tree_id = 0
    return Header(
        command=command,
        status=status,
        flags=flags,
        next_command=next_command,
        message_id=message_id,
        tree_id=tree_id,
        session_id=session_id,
        credit_charge=credit_charge,
        credit_request=credit_request,
        signature=signature,
    )


def pack_message(header: Header, body: bytes) -> bytes:
    fixed = _HEADER.pack(
        SMB2_MAGIC,
        SMB2_STRUCTURE_SIZE,
        header.credit_charge,
        header.status,
        header.command,
        header.credit_request,
        header.flags,
        header.next_command,
        header.message_id,
        0,
        header.tree_id,
        header.session_id,
        header.signature,
    )
    return fixed + body


def frame_message(payload: bytes) -> bytes:
    return bytes([NBSS_MESSAGE]) + len(payload).to_bytes(3, "big") + payload


async def read_frame(connection: _Reader, limit: int) -> bytes:
    """The next NetBIOS session message's payload; keep-alives are skipped, anything else ends."""
    while True:
        prefix = await connection.read_exactly(NBSS_HEADER_BYTES)
        if prefix[0] == NBSS_KEEP_ALIVE:
            continue
        if prefix[0] != NBSS_MESSAGE:
            raise SmbFormatError(f"NetBIOS message type {prefix[0]:#x}")
        length = int.from_bytes(prefix[1:], "big")
        if length == 0 or length > limit:
            raise SmbFormatError(f"a frame of {length} bytes")
        return await connection.read_exactly(length)


def split_compound(frame: bytes) -> list[bytes]:
    """The messages of one frame: a related chain is several, each starting 8-byte aligned."""
    messages: list[bytes] = []
    offset = 0
    while True:
        if len(messages) >= MAX_COMPOUND_MESSAGES:
            raise SmbFormatError("too many compounded messages")
        header = parse_header(frame[offset : offset + HEADER_SIZE])
        step = header.next_command
        if step == 0:
            messages.append(frame[offset:])
            return messages
        if step % COMPOUND_ALIGNMENT or step <= HEADER_SIZE:
            raise SmbFormatError("a compound offset is misaligned or inside the header")
        if offset + step + HEADER_SIZE > len(frame):
            raise SmbFormatError("a compound offset points past the frame")
        messages.append(frame[offset : offset + step])
        offset += step


def parse_smb1_negotiate(payload: bytes) -> Smb1Negotiate:
    """The dialect names of an SMB1 NEGOTIATE request, which is all this server reads of SMB1."""
    counts_at = SMB1_HEADER_BYTES
    if len(payload) < counts_at + _SMB1_COUNTS.size or payload[:4] != SMB1_MAGIC:
        raise SmbFormatError("not an SMB1 message")
    if payload[4] != SMB1_NEGOTIATE_COMMAND:
        raise SmbFormatError("an SMB1 message that is not a negotiate")
    word_count, byte_count = _SMB1_COUNTS.unpack_from(payload, counts_at)
    names_at = counts_at + _SMB1_COUNTS.size
    if word_count != 0 or names_at + byte_count > len(payload):
        raise SmbFormatError("a malformed SMB1 negotiate")
    names = tuple(_smb1_dialects(payload[names_at : names_at + byte_count]))
    return Smb1Negotiate(
        dialects=names,
        offers_smb2_wildcard=SMB1_WILDCARD_DIALECT in names,
        offers_smb2_002=SMB1_SMB2_002_DIALECT in names,
    )


def smb1_negotiate_refusal() -> bytes:
    """The SMB1 NEGOTIATE reply that says no dialect is acceptable.

    Windows answers with status success and dialect index 0xFFFF; nmap recognises SMB by it.
    """
    return _SMB1_REFUSAL.pack(
        SMB1_MAGIC,
        SMB1_NEGOTIATE_COMMAND,
        SMB1_STATUS_SUCCESS,
        SMB1_NEGOTIATE_REPLY_FLAGS,
        SMB1_NEGOTIATE_REPLY_FLAGS2,
        0,
        bytes(8),
        0,
        0,
        0,
        0,
        0,
        1,
        SMB1_NO_COMMON_DIALECT,
        0,
    )


def _smb1_dialects(region: bytes) -> list[str]:
    names: list[str] = []
    position = 0
    while position < len(region):
        if region[position] != SMB1_DIALECT_MARKER or len(names) >= MAX_SMB1_DIALECTS:
            raise SmbFormatError("a malformed SMB1 dialect list")
        end = region.find(b"\x00", position + 1)
        if end < 0:
            raise SmbFormatError("an unterminated SMB1 dialect name")
        names.append(region[position + 1 : end].decode("ascii", "replace"))
        position = end + 1
    return names
