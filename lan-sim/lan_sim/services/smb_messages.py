"""The bodies of the SMB2 commands this server speaks: parsed from requests, built for replies.

Request parsers are strict about structure sizes, offsets and lengths and raise `SmbFormatError`;
they never index past the bytes they were given. Offsets inside a body are relative to the start
of the message, so the body's own index is the offset minus the 64-byte header.
"""

import struct
from typing import NamedTuple

from lan_sim.services.smb_wire import HEADER_SIZE, SmbFormatError

# Commands
NEGOTIATE, SESSION_SETUP, LOGOFF, TREE_CONNECT, TREE_DISCONNECT = range(5)
CREATE, CLOSE, FLUSH, READ, WRITE, LOCK, IOCTL, CANCEL, ECHO = range(5, 14)
QUERY_DIRECTORY, CHANGE_NOTIFY, QUERY_INFO, SET_INFO, OPLOCK_BREAK = range(14, 19)

FILE_ID_BYTES = 16
ANY_FILE = b"\xff" * FILE_ID_BYTES
MAX_NAME_BYTES = 1024
MAX_SECURITY_BUFFER_BYTES = 16 * 1024 + 512
MAX_NEGOTIATE_DIALECTS = 64
MAX_NEGOTIATE_CONTEXTS = 16
MAX_IOCTL_INPUT_BYTES = 64 * 1024

SECURITY_SIGNING_ENABLED = 0x1
SECURITY_SIGNING_REQUIRED = 0x2
PREAUTH_INTEGRITY_CONTEXT = 1
SHA512_ID = 1
DIALECT_3_1_1 = 0x0311
CONTEXT_FIXED_BYTES = 4
PREAUTH_SALT_BYTES = 32
SHARE_TYPE_DISK, SHARE_TYPE_PIPE = 1, 2

_NEGOTIATE = struct.Struct("<HHHHI16s8s")
_NEGOTIATE_CONTEXT_FIELDS = struct.Struct("<IHH")
_CONTEXT_HEADER = struct.Struct("<HHI")
_SESSION_SETUP = struct.Struct("<HBBIIHHQ")
_TREE_CONNECT = struct.Struct("<HHHH")
_CREATE = struct.Struct("<HBBIQQIIIIIHHII")
_CLOSE = struct.Struct("<HHI16s")
_READ = struct.Struct("<HBBIQ16sIIIHH")
_WRITE = struct.Struct("<HHIQ16sIIHHI")
_QUERY_INFO = struct.Struct("<HBBIHHIII16s")
_SET_INFO = struct.Struct("<HBBIHHI16s")
_QUERY_DIRECTORY = struct.Struct("<HBBI16sHHI")
_IOCTL = struct.Struct("<HHI16sIIIIIIII")


class NegotiateRequest(NamedTuple):
    dialects: tuple[int, ...]
    security_mode: int
    offers_sha512: bool


class CreateRequest(NamedTuple):
    desired_access: int
    file_attributes: int
    disposition: int
    options: int
    name: str


class ReadRequest(NamedTuple):
    length: int
    offset: int
    file_id: bytes


class WriteRequest(NamedTuple):
    offset: int
    file_id: bytes
    data: bytes


class QueryInfoRequest(NamedTuple):
    info_type: int
    info_class: int
    output_length: int
    file_id: bytes


class SetInfoRequest(NamedTuple):
    info_type: int
    info_class: int
    file_id: bytes
    buffer: bytes


class QueryDirectoryRequest(NamedTuple):
    info_class: int
    flags: int
    file_id: bytes
    pattern: str
    output_length: int


class IoctlRequest(NamedTuple):
    code: int
    file_id: bytes
    data: bytes
    max_output: int


def _unpack(layout: struct.Struct, body: bytes, structure_size: int) -> tuple:
    """The fixed fields; the structure size counts one byte of the variable part."""
    if len(body) < layout.size or struct.unpack_from("<H", body)[0] != structure_size:
        raise SmbFormatError(f"a body of the wrong size or structure ({structure_size})")
    return layout.unpack_from(body)


def _region(body: bytes, offset: int, length: int, limit: int) -> bytes:
    if length > limit:
        raise SmbFormatError("a field longer than this server accepts")
    if length == 0:
        return b""
    start = offset - HEADER_SIZE
    if start < 0 or start + length > len(body):
        raise SmbFormatError("a field points outside the message")
    return body[start : start + length]


def _utf16(raw: bytes) -> str:
    if len(raw) % 2:
        raise SmbFormatError("a UTF-16 name of odd length")
    try:
        return raw.decode("utf-16le")
    except UnicodeDecodeError as error:
        raise SmbFormatError("a name that is not UTF-16") from error


def parse_negotiate(body: bytes) -> NegotiateRequest:
    fixed = _unpack(_NEGOTIATE, body, 36)
    count, security_mode, _, _, _, tail = fixed[1:7]
    if not 1 <= count <= MAX_NEGOTIATE_DIALECTS or len(body) < _NEGOTIATE.size + 2 * count:
        raise SmbFormatError("a bad dialect count")
    dialects = struct.unpack_from(f"<{count}H", body, _NEGOTIATE.size)
    offers_sha512 = False
    if DIALECT_3_1_1 in dialects:
        offset, context_count, _ = _NEGOTIATE_CONTEXT_FIELDS.unpack(tail)
        offers_sha512 = _offers_sha512(body, offset, context_count)
    return NegotiateRequest(tuple(dialects), security_mode, offers_sha512)


def _offers_sha512(body: bytes, offset: int, count: int) -> bool:
    if count > MAX_NEGOTIATE_CONTEXTS:
        raise SmbFormatError("too many negotiate contexts")
    position = offset - HEADER_SIZE
    found = False
    for _ in range(count):
        position += -position % 8
        if position < 0 or position + _CONTEXT_HEADER.size > len(body):
            raise SmbFormatError("a negotiate context is cut short")
        kind, length, _ = _CONTEXT_HEADER.unpack_from(body, position)
        data = body[position + _CONTEXT_HEADER.size : position + _CONTEXT_HEADER.size + length]
        if len(data) != length:
            raise SmbFormatError("a negotiate context is cut short")
        found = found or (kind == PREAUTH_INTEGRITY_CONTEXT and _lists_sha512(data))
        position += _CONTEXT_HEADER.size + length
    return found


def _lists_sha512(data: bytes) -> bool:
    if len(data) < CONTEXT_FIXED_BYTES:
        return False
    algorithms, _salt = struct.unpack_from("<HH", data)
    if len(data) < CONTEXT_FIXED_BYTES + 2 * algorithms:
        return False
    return SHA512_ID in struct.unpack_from(f"<{algorithms}H", data, CONTEXT_FIXED_BYTES)


def negotiate_response(  # noqa: PLR0913 - the fields of the message
    *, dialect: int, guid: bytes, now: int, max_size: int, security: bytes, salt: bytes | None
) -> bytes:
    """The NEGOTIATE reply; `salt` adds the 3.1.1 pre-authentication integrity context."""
    security_offset = HEADER_SIZE + 64
    padding = bytes(-len(security) % 8)
    contexts = b""
    context_offset = 0
    if salt is not None:
        data = struct.pack("<HHH", 1, len(salt), SHA512_ID) + salt
        contexts = _CONTEXT_HEADER.pack(PREAUTH_INTEGRITY_CONTEXT, len(data), 0) + data
        context_offset = security_offset + len(security) + len(padding)
    fixed = struct.pack(
        "<HHHH16sIIIIQQHHI",
        65,
        SECURITY_SIGNING_ENABLED | SECURITY_SIGNING_REQUIRED,
        dialect,
        1 if salt is not None else 0,
        guid,
        0,
        max_size,
        max_size,
        max_size,
        now,
        0,
        security_offset,
        len(security),
        context_offset,
    )
    return fixed + security + (padding + contexts if contexts else b"")


def parse_session_setup(body: bytes) -> bytes:
    fixed = _unpack(_SESSION_SETUP, body, 25)
    return _region(body, fixed[5], fixed[6], MAX_SECURITY_BUFFER_BYTES)


def session_setup_response(security: bytes) -> bytes:
    return struct.pack("<HHHH", 9, 0, HEADER_SIZE + 8, len(security)) + security


def parse_tree_connect(body: bytes) -> str:
    fixed = _unpack(_TREE_CONNECT, body, 9)
    return _utf16(_region(body, fixed[2], fixed[3], MAX_NAME_BYTES))


def tree_connect_response(share_type: int, access: int) -> bytes:
    return struct.pack("<HBBIII", 16, share_type, 0, 0x30, 0, access)


def parse_create(body: bytes) -> CreateRequest:
    fixed = _unpack(_CREATE, body, 57)
    name = _utf16(_region(body, fixed[11], fixed[12], MAX_NAME_BYTES))
    return CreateRequest(
        desired_access=fixed[6],
        file_attributes=fixed[7],
        disposition=fixed[9],
        options=fixed[10],
        name=name,
    )


def create_response(  # noqa: PLR0913 - the fields of the message
    *,
    action: int,
    times: tuple[int, int, int, int],
    allocation: int,
    size: int,
    attributes: int,
    file_id: bytes,
) -> bytes:
    return (
        struct.pack(
            "<HBBI4Q2QII16sII",
            89,
            0,
            0,
            action,
            *times,
            allocation,
            size,
            attributes,
            0,
            file_id,
            0,
            0,
        )
        + b"\x00"
    )


def parse_close(body: bytes) -> bytes:
    return _unpack(_CLOSE, body, 24)[3]


def close_response(
    *, times: tuple[int, int, int, int], allocation: int, size: int, attributes: int
) -> bytes:
    return struct.pack("<HHI4Q2QI", 60, 1, 0, *times, allocation, size, attributes)


def parse_file_id_only(body: bytes, structure_size: int) -> bytes:
    """FLUSH and LOCK name a file at offset 8; nothing else of them is read."""
    if len(body) < 8 + FILE_ID_BYTES or struct.unpack_from("<H", body)[0] != structure_size:
        raise SmbFormatError("a body of the wrong size")
    return body[8 : 8 + FILE_ID_BYTES]


def empty_response() -> bytes:
    return struct.pack("<HH", 4, 0)


def error_response() -> bytes:
    return struct.pack("<HBBIB", 9, 0, 0, 0, 0)


def parse_read(body: bytes) -> ReadRequest:
    fixed = _unpack(_READ, body, 49)
    return ReadRequest(length=fixed[3], offset=fixed[4], file_id=fixed[5])


def read_response(data: bytes) -> bytes:
    return struct.pack("<HBBIII", 17, HEADER_SIZE + 16, 0, len(data), 0, 0) + data


def parse_write(body: bytes, limit: int) -> WriteRequest:
    fixed = _unpack(_WRITE, body, 49)
    return WriteRequest(
        offset=fixed[3], file_id=fixed[4], data=_region(body, fixed[1], fixed[2], limit)
    )


def write_response(count: int) -> bytes:
    return struct.pack("<HHIIHH", 17, 0, count, 0, 0, 0) + b"\x00"


def parse_query_info(body: bytes) -> QueryInfoRequest:
    fixed = _unpack(_QUERY_INFO, body, 41)
    return QueryInfoRequest(
        info_type=fixed[1], info_class=fixed[2], output_length=fixed[3], file_id=fixed[9]
    )


def parse_set_info(body: bytes) -> SetInfoRequest:
    fixed = _unpack(_SET_INFO, body, 33)
    buffer = _region(body, fixed[4], fixed[3], MAX_NAME_BYTES + 64)
    return SetInfoRequest(info_type=fixed[1], info_class=fixed[2], file_id=fixed[7], buffer=buffer)


def set_info_response() -> bytes:
    return struct.pack("<H", 2)


def parse_query_directory(body: bytes) -> QueryDirectoryRequest:
    fixed = _unpack(_QUERY_DIRECTORY, body, 33)
    pattern = _utf16(_region(body, fixed[5], fixed[6], MAX_NAME_BYTES))
    return QueryDirectoryRequest(
        info_class=fixed[1],
        flags=fixed[2],
        file_id=fixed[4],
        pattern=pattern,
        output_length=fixed[7],
    )


def output_response(data: bytes) -> bytes:
    """QUERY_DIRECTORY and QUERY_INFO share one reply shape."""
    return struct.pack("<HHI", 9, HEADER_SIZE + 8, len(data)) + data


def parse_ioctl(body: bytes) -> IoctlRequest:
    fixed = _unpack(_IOCTL, body, 57)
    data = _region(body, fixed[4], fixed[5], MAX_IOCTL_INPUT_BYTES)
    return IoctlRequest(code=fixed[2], file_id=fixed[3], data=data, max_output=fixed[9])


def ioctl_response(code: int, file_id: bytes, output: bytes) -> bytes:
    fixed = struct.pack(
        "<HHI16sIIIIII", 49, 0, code, file_id, 0, 0, HEADER_SIZE + 48, len(output), 0, 0
    )
    return fixed + output
