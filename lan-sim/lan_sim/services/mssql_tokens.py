"""The tokens of a tabular reply, laid out for the TDS version the client announced.

Below TDS 7.2 the column UserType is 2 bytes, the DONE row count 4 bytes and the error line number
2 bytes; from 7.2 they are 4, 8 and 4 (MS-TDS 2.2.7). A client parses with the layout of the version
it asked for, so a reply in the wrong one desynchronises it.
"""

import struct

from lan_sim.services.mssql_wire import SERVER_VERSION, TdsVersion

TOKEN_LOGIN_ACK = 0xAD
TOKEN_ENV_CHANGE = 0xE3
TOKEN_INFO = 0xAB
TOKEN_ERROR = 0xAA
TOKEN_DONE = 0xFD
TOKEN_SSPI = 0xED
TOKEN_COLUMN_METADATA = 0x81
TOKEN_ROW = 0xD1

ENV_DATABASE = 1
ENV_PACKET_SIZE = 4
DONE_ERROR = 0x02
DONE_COUNT = 0x10
DONE_ATTENTION = 0x20
COMMAND_SELECT = 0xC1

LOGIN_FAILED = 18456
DATABASE_CONTEXT_CHANGED = 5701
ERROR_STATE = 1
ERROR_CLASS = 14
INFO_STATE = 2
INFO_CLASS = 0

TYPE_NVARCHAR = 0xE7
NVARCHAR_4000_BYTES = 8000
NVARCHAR_NULL = 0xFFFF
COLUMN_FLAGS = 0x21
# SQL_Latin1_General_CP1_CI_AS, the collation every default install reports.
COLLATION = bytes.fromhex("0904d00034")
MAX_NAME_CHARACTERS = 128
MAX_MESSAGE_CHARACTERS = 2000
PROGRAM_NAME = "Microsoft SQL Server"
DEFAULT_DATABASE = "master"
PACKET_SIZE_TEXT = "4096"


def _b_varchar(text: str) -> bytes:
    text = text[:MAX_NAME_CHARACTERS]
    return bytes([len(text)]) + text.encode("utf-16le", errors="replace")


def _us_varchar(text: str) -> bytes:
    text = text[:MAX_MESSAGE_CHARACTERS]
    return struct.pack("<H", len(text)) + text.encode("utf-16le", errors="replace")


def _token(token_type: int, body: bytes) -> bytes:
    return bytes([token_type]) + struct.pack("<H", len(body)) + body


def sspi_token(blob: bytes) -> bytes:
    return _token(TOKEN_SSPI, blob)


def env_change(kind: int, new_value: str, old_value: str) -> bytes:
    return _token(TOKEN_ENV_CHANGE, bytes([kind]) + _b_varchar(new_value) + _b_varchar(old_value))


def done(
    version: TdsVersion,
    *,
    rows: int | None = None,
    error: bool = False,
    attention: bool = False,
) -> bytes:
    status = DONE_COUNT if rows is not None else 0
    status |= DONE_ERROR if error else 0
    status |= DONE_ATTENTION if attention else 0
    command = COMMAND_SELECT if rows is not None else 0
    count_format = "<I" if version.legacy_layout else "<Q"
    return (
        bytes([TOKEN_DONE])
        + struct.pack("<HH", status, command)
        + struct.pack(count_format, rows or 0)
    )


def _message(token_type: int, version: TdsVersion, header: bytes, text: str, server: str) -> bytes:
    line_format = "<H" if version.legacy_layout else "<I"
    body = header + _us_varchar(text) + _b_varchar(server) + _b_varchar("")
    return _token(token_type, body + struct.pack(line_format, 1))


def error_message(version: TdsVersion, number: int, text: str, server: str) -> bytes:
    header = struct.pack("<IBB", number, ERROR_STATE, ERROR_CLASS)
    return _message(TOKEN_ERROR, version, header, text, server)


def info_message(version: TdsVersion, number: int, text: str, server: str) -> bytes:
    header = struct.pack("<IBB", number, INFO_STATE, INFO_CLASS)
    return _message(TOKEN_INFO, version, header, text, server)


def login_failure(version: TdsVersion, server: str, user: str) -> bytes:
    text = f"Login failed for user '{user[:MAX_NAME_CHARACTERS]}'."
    return error_message(version, LOGIN_FAILED, text, server) + done(version, error=True)


def login_success(version: TdsVersion, server: str) -> bytes:
    major, minor, build, _ = SERVER_VERSION
    acknowledgement = bytes([1]) + struct.pack(">I", version.acknowledged)
    acknowledgement += _b_varchar(PROGRAM_NAME) + bytes([major, minor]) + struct.pack(">H", build)
    return (
        _token(TOKEN_LOGIN_ACK, acknowledgement)
        + env_change(ENV_DATABASE, DEFAULT_DATABASE, DEFAULT_DATABASE)
        + env_change(ENV_PACKET_SIZE, PACKET_SIZE_TEXT, PACKET_SIZE_TEXT)
        + info_message(
            version,
            DATABASE_CONTEXT_CHANGED,
            f"Changed database context to '{DEFAULT_DATABASE}'.",
            server,
        )
        + done(version)
    )


def scalar_result(version: TdsVersion, column: str, value: str | None) -> bytes:
    """One NVARCHAR(4000) column named `column` with one row, or a NULL when `value` is None."""
    user_type_format = "<H" if version.legacy_layout else "<I"
    metadata = bytes([TOKEN_COLUMN_METADATA]) + struct.pack("<H", 1)
    metadata += struct.pack(user_type_format, 0) + struct.pack("<H", COLUMN_FLAGS)
    metadata += bytes([TYPE_NVARCHAR]) + struct.pack("<H", NVARCHAR_4000_BYTES) + COLLATION
    metadata += _b_varchar(column)
    if value is None:
        row = bytes([TOKEN_ROW]) + struct.pack("<H", NVARCHAR_NULL)
    else:
        encoded = value[: NVARCHAR_4000_BYTES // 2].encode("utf-16le", errors="replace")
        row = bytes([TOKEN_ROW]) + struct.pack("<H", len(encoded)) + encoded
    return metadata + row + done(version, rows=1)
