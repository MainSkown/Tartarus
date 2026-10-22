import base64
import json

import pytest

from app.errors import ApiError
from app.events.cursor import decode_cursor, encode_cursor

SORT_VALUES = [1760357562383, 42, "e7a155f42c5b3afa"]


def test_a_cursor_round_trips_its_sort_values() -> None:
    cursor = encode_cursor("@timestamp", SORT_VALUES)

    assert decode_cursor(cursor, "@timestamp") == SORT_VALUES


def test_a_cursor_is_url_safe_text_without_padding() -> None:
    cursor = encode_cursor("-@timestamp", [-9223372036854775808, 1, "ünï/cödé?"])

    assert all(character.isalnum() or character in "-_" for character in cursor)


def test_a_cursor_is_opaque_json_in_base64url() -> None:
    cursor = encode_cursor("@timestamp", SORT_VALUES)

    padded = cursor + "=" * (-len(cursor) % 4)
    assert json.loads(base64.urlsafe_b64decode(padded)) == {
        "sort": "@timestamp",
        "after": SORT_VALUES,
    }


def encoded(payload: object) -> str:
    raw = json.dumps(payload).encode() if not isinstance(payload, bytes) else payload
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


@pytest.mark.parametrize(
    "cursor",
    [
        "",
        "!!not base64!!",
        encoded(b"not json"),
        encoded([1, 2, 3]),
        encoded({"sort": "@timestamp"}),
        encoded({"sort": "@timestamp", "after": [1, 2]}),
        encoded({"sort": "@timestamp", "after": [1, 2, 3]}),
        encoded({"sort": "@timestamp", "after": ["a", 2, "c"]}),
        encoded({"sort": "@timestamp", "after": [1.5, 2, "c"]}),
        encoded({"sort": "@timestamp", "after": [True, 2, "c"]}),
        encoded({"sort": "@timestamp", "after": [1, 2, "c", "d"]}),
    ],
)
def test_a_malformed_cursor_is_a_422(cursor: str) -> None:
    with pytest.raises(ApiError) as caught:
        decode_cursor(cursor, "@timestamp")

    assert caught.value.status_code == 422
    assert caught.value.code == "invalid_cursor"


def test_a_cursor_from_the_other_sort_is_refused() -> None:
    cursor = encode_cursor("-@timestamp", SORT_VALUES)

    with pytest.raises(ApiError) as caught:
        decode_cursor(cursor, "@timestamp")

    assert "other sort" in caught.value.message


def test_a_cursor_nested_deeper_than_the_json_parser_allows_is_an_invalid_cursor() -> None:
    nested = base64.urlsafe_b64encode(b"[" * 200_000).decode().rstrip("=")

    with pytest.raises(ApiError) as caught:
        decode_cursor(nested, "@timestamp")

    assert caught.value.code == "invalid_cursor"
