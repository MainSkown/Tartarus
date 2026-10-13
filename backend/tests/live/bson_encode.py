import struct
from datetime import UTC, datetime
from typing import Any


class Binary(bytes):
    """Marks bytes to be encoded as a BSON binary element rather than refused."""


def encode_document(document: dict[str, Any]) -> bytes:
    body = b"".join(_element(name, value) for name, value in document.items())
    return struct.pack("<i", len(body) + 5) + body + b"\x00"


def _element(name: str, value: Any) -> bytes:
    key = name.encode() + b"\x00"
    match value:
        case dict():
            return b"\x03" + key + encode_document(value)
        case list():
            return b"\x04" + key + encode_document({str(i): item for i, item in enumerate(value)})
        case str():
            raw = value.encode() + b"\x00"
            return b"\x02" + key + struct.pack("<i", len(raw)) + raw
        case Binary():
            return b"\x05" + key + struct.pack("<i", len(value)) + b"\x00" + value
        case datetime():
            return b"\x09" + key + struct.pack("<q", int(value.astimezone(UTC).timestamp() * 1000))
    return _scalar_element(key, value)


def _scalar_element(key: bytes, value: Any) -> bytes:
    match value:
        case bool():
            return b"\x08" + key + (b"\x01" if value else b"\x00")
        case None:
            return b"\x0a" + key
        case int() if -(2**31) <= value < 2**31:
            return b"\x10" + key + struct.pack("<i", value)
        case int():
            return b"\x12" + key + struct.pack("<q", value)
        case float():
            return b"\x01" + key + struct.pack("<d", value)
    raise TypeError(f"cannot encode {type(value).__name__}")
