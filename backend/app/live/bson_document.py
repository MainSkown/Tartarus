import struct
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

MAX_NESTING = 64
_MIN_DOCUMENT_SIZE = 5

_INT32 = struct.Struct("<i")
_INT64 = struct.Struct("<q")
_DOUBLE = struct.Struct("<d")


class BsonError(ValueError):
    """The bytes are not a well-formed BSON document of the subset the capemon logs use."""


def decode_document(data: bytes | bytearray | memoryview) -> dict[str, Any]:
    """Decode one complete BSON document.

    Binary elements come back as ``bytes`` and arrays as ``list``; invalid UTF-8 inside a string
    is replaced, not fatal, because the monitor logs whatever the guest handed it.
    """
    document, end = _document(bytes(data), 0, 0)
    if end != len(data):
        raise BsonError(f"document declares {end} bytes but {len(data)} were given")
    return document


def _document(data: bytes, start: int, depth: int) -> tuple[dict[str, Any], int]:
    if depth > MAX_NESTING:
        raise BsonError("documents are nested too deeply")
    size = _read(_INT32, data, start)
    end = start + size
    if size < _MIN_DOCUMENT_SIZE or end > len(data):
        raise BsonError(f"document size {size} does not fit the available bytes")
    if data[end - 1] != 0:
        raise BsonError("document is not terminated by a zero byte")
    document: dict[str, Any] = {}
    position = start + 4
    while position < end - 1:
        name, value, position = _element(data, position, end - 1, depth)
        document[name] = value
    if position != end - 1:
        raise BsonError("an element runs into the document terminator")
    return document, end


def _element(data: bytes, position: int, limit: int, depth: int) -> tuple[str, Any, int]:
    type_byte = data[position]
    name_end = data.find(b"\x00", position + 1, limit)
    if name_end < 0:
        raise BsonError("element name is not terminated")
    name = data[position + 1 : name_end].decode("utf-8", errors="replace")
    value, after = _value(type_byte, data, name_end + 1, limit, depth)
    if after > limit:
        raise BsonError(f"element {name!r} runs past the end of its document")
    return name, value, after


_FIXED_SIZE_VALUES = {0x01: _DOUBLE, 0x10: _INT32, 0x12: _INT64}


def _value(type_byte: int, data: bytes, position: int, limit: int, depth: int) -> tuple[Any, int]:
    if (layout := _FIXED_SIZE_VALUES.get(type_byte)) is not None:
        return _read(layout, data, position), position + layout.size
    if (reader := _BOUNDED_READERS.get(type_byte)) is not None:
        return reader(data, position, limit)
    return _structured_value(type_byte, data, position, depth)


def _structured_value(type_byte: int, data: bytes, position: int, depth: int) -> tuple[Any, int]:
    match type_byte:
        case 0x03:
            return _document(data, position, depth + 1)
        case 0x04:
            document, after = _document(data, position, depth + 1)
            return list(document.values()), after
        case 0x09:
            return _datetime(_read(_INT64, data, position)), position + 8
        case 0x0A:
            return None, position
    raise BsonError(f"unsupported element type 0x{type_byte:02x}")


def _datetime(millis: int) -> datetime:
    try:
        return datetime.fromtimestamp(millis / 1000, UTC)
    except (OverflowError, OSError, ValueError) as error:
        raise BsonError(f"datetime of {millis} ms is outside the supported years") from error


def _string(data: bytes, position: int, limit: int) -> tuple[str, int]:
    size = _read(_INT32, data, position)
    start = position + 4
    end = start + size
    if size < 1 or end > limit or data[end - 1] != 0:
        raise BsonError("string is not length-prefixed and zero-terminated")
    return data[start : end - 1].decode("utf-8", errors="replace"), end


def _binary(data: bytes, position: int, limit: int) -> tuple[bytes, int]:
    size = _read(_INT32, data, position)
    start = position + 5  # the subtype byte is ignored: the monitor only emits generic binary
    end = start + size
    if size < 0 or end > limit:
        raise BsonError("binary element runs past the end of its document")
    return data[start:end], end


def _boolean(data: bytes, position: int, limit: int) -> tuple[bool, int]:
    if position >= limit or data[position] > 1:
        raise BsonError("boolean is not 0 or 1")
    return data[position] == 1, position + 1


def _read(layout: struct.Struct, data: bytes, position: int) -> Any:
    if position + layout.size > len(data):
        raise BsonError("value runs past the end of the data")
    return layout.unpack_from(data, position)[0]


_BOUNDED_READERS: dict[int, Callable[[bytes, int, int], tuple[Any, int]]] = {
    0x02: _string,
    0x05: _binary,
    0x08: _boolean,
}
