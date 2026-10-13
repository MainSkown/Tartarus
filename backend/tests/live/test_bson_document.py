import struct
from datetime import UTC, datetime

import pytest

from app.live.bson_document import BsonError, decode_document
from tests.live.bson_encode import Binary, encode_document


def test_decodes_every_supported_element_type() -> None:
    moment = datetime(2026, 10, 13, 15, 39, 50, 393000, tzinfo=UTC)
    document = {
        "small": 7,
        "negative": -5,
        "big": 2**40,
        "ratio": 1.5,
        "text": "zażółć",
        "blob": Binary(b"C:\\a\x00b"),
        "yes": True,
        "no": False,
        "nothing": None,
        "moment": moment,
        "nested": {"inner": 1},
        "items": [1, "two", Binary(b"3")],
    }

    assert decode_document(encode_document(document)) == document


def test_keeps_element_order() -> None:
    document = {"b": 1, "a": 2, "c": 3}

    assert list(decode_document(encode_document(document))) == ["b", "a", "c"]


def test_empty_document_is_empty_dict() -> None:
    assert decode_document(encode_document({})) == {}


@pytest.mark.parametrize(
    ("mutate", "reason"),
    [
        (lambda raw: raw[:-1], "shorter than declared"),
        (lambda raw: raw + b"\x00", "longer than declared"),
        (lambda raw: raw[:-1] + b"\x01", "missing terminator"),
        (lambda raw: struct.pack("<i", 4) + raw[4:], "declared length below minimum"),
        (lambda raw: raw[:4] + b"\x7f" + raw[5:], "unknown element type"),
    ],
)
def test_rejects_malformed_documents(mutate, reason: str) -> None:  # type: ignore[no-untyped-def]
    raw = encode_document({"a": 1, "b": "text"})

    with pytest.raises(BsonError):
        decode_document(mutate(raw))


def test_rejects_string_without_terminator() -> None:
    element = b"\x02a\x00" + struct.pack("<i", 2) + b"xy"
    raw = struct.pack("<i", len(element) + 5) + element + b"\x00"

    with pytest.raises(BsonError):
        decode_document(raw)


def test_rejects_element_running_past_the_document() -> None:
    element = b"\x12a\x00" + b"\x01\x00"
    raw = struct.pack("<i", len(element) + 5) + element + b"\x00"

    with pytest.raises(BsonError):
        decode_document(raw)


def test_rejects_excessive_nesting() -> None:
    document: dict[str, object] = {}
    for _ in range(200):
        document = {"d": document}

    with pytest.raises(BsonError):
        decode_document(encode_document(document))


def test_invalid_utf8_in_a_string_is_replaced_not_fatal() -> None:
    element = b"\x02a\x00" + struct.pack("<i", 3) + b"\xff\xfe\x00"
    raw = struct.pack("<i", len(element) + 5) + element + b"\x00"

    assert decode_document(raw) == {"a": "\ufffd\ufffd"}
