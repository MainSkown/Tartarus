"""The `search_after` cursor: the sort values of the last event of a page, as opaque text."""

import base64
import binascii
import json
from collections.abc import Sequence
from typing import TypeGuard

from app.errors import ApiError
from app.schemas.events_api import SortOrder

type SortValue = int | str

SORT_VALUE_SHAPE = (int, int, str)


def _invalid(message: str) -> ApiError:
    return ApiError(422, "invalid_cursor", message)


def encode_cursor(sort: SortOrder, sort_values: Sequence[SortValue]) -> str:
    payload = json.dumps({"sort": sort, "after": list(sort_values)}, separators=(",", ":"))
    return base64.urlsafe_b64encode(payload.encode()).decode().rstrip("=")


def decode_cursor(cursor: str, sort: SortOrder) -> list[SortValue]:
    payload = _payload(cursor)
    if payload.get("sort") != sort:
        raise _invalid("The cursor was issued for the other sort order")
    after = payload.get("after")
    if not _has_sort_value_shape(after):
        raise _invalid("The cursor is malformed")
    return after


def _payload(cursor: str) -> dict[str, object]:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")))
    except (binascii.Error, ValueError):
        raise _invalid("The cursor is malformed") from None
    if not isinstance(payload, dict):
        raise _invalid("The cursor is malformed")
    return payload


def _has_sort_value_shape(after: object) -> TypeGuard[list[SortValue]]:
    return (
        isinstance(after, list)
        and len(after) == len(SORT_VALUE_SHAPE)
        and all(
            isinstance(value, kind) and not isinstance(value, bool)
            for value, kind in zip(after, SORT_VALUE_SHAPE, strict=True)
        )
    )
