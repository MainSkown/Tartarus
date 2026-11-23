"""The event schema: what each event type carries, and the cleaning every string goes through.

`SCHEMA.md` documents the same table for the reader of the log. The text of an event comes from a
client, so every string is stripped of control characters and cut to a cap before it is written:
a hostile username must not break the JSONL or a report that later renders it as HTML.
"""

import re
import unicodedata
from collections.abc import Callable, Mapping
from typing import Any, NamedTuple

from lan_sim.limits import Limits

EVENT_TYPES = (
    "connection",
    "login-attempt",
    "share-access",
    "file-write",
    "service-request",
    "aggregate",
    "session-end",
)
MECHANISMS = ("ntlm", "basic", "password", "publickey", "sql", "ldap-simple")


class Endpoint(NamedTuple):
    ip: str
    port: int


MAX_COUNT = 2**63 - 1
SHA256 = re.compile(r"[0-9a-f]{64}")
ELLIPSIS = "…"
REPLACEMENT = "�"
DROPPED_CATEGORIES = {"Cc", "Cf", "Co", "Cn", "Zl", "Zp"}
SURROGATE = "Cs"


def _clean_character(character: str) -> str:
    category = unicodedata.category(character)
    if category == SURROGATE:
        return REPLACEMENT
    return "" if category in DROPPED_CATEGORIES else character


def sanitize_text(value: str | bytes, max_length: int) -> str:
    """The printable part of `value`, at most `max_length` characters; an ellipsis marks a cut."""
    if isinstance(value, bytes | bytearray):
        value = bytes(value[: max_length + 1]).decode("utf-8", errors="replace")
    cut = len(value) > max_length
    # Only the head is scanned: a 10 MB string costs no more than a short one.
    cleaned = "".join(_clean_character(character) for character in value[: max_length + 1])
    if cut:
        return cleaned[: max_length - 1] + ELLIPSIS
    return cleaned[:max_length]


def _count(value: Any) -> int:
    return max(0, min(int(value), MAX_COUNT))


def _flag(value: Any) -> bool:
    if not isinstance(value, bool):
        raise ValueError("a flag must be a bool")
    return value


def _mechanism(value: Any) -> str:
    if value not in MECHANISMS:
        raise ValueError(f"mechanism must be one of {', '.join(MECHANISMS)}")
    return str(value)


def _sha256(value: Any) -> str:
    if not isinstance(value, str) or not SHA256.fullmatch(value):
        raise ValueError("sha256 must be 64 lowercase hex digits")
    return value


def _identity(limits: Limits) -> Callable[[Any], str]:
    return lambda value: sanitize_text(value, limits.max_identity_length)


def _path(limits: Limits) -> Callable[[Any], str]:
    return lambda value: sanitize_text(value, limits.max_path_length)


def _secret(limits: Limits) -> Callable[[Any], str]:
    return lambda value: sanitize_text(value, limits.max_secret_length)


def _cleaners(limits: Limits) -> Mapping[str, Mapping[str, Callable[[Any], Any]]]:
    identity, path, secret = _identity(limits), _path(limits), _secret(limits)
    return {
        "connection": {"bytes_in": _count, "bytes_out": _count, "duration_ms": _count},
        "login-attempt": {
            "user": identity,
            "domain": identity,
            "mechanism": _mechanism,
            "secret": secret,
            "success": _flag,
        },
        "share-access": {"share": identity, "path": path, "operation": identity},
        "file-write": {
            "share": identity,
            "path": path,
            "size": _count,
            "sha256": _sha256,
            "truncated": _flag,
        },
        "service-request": {"name": identity, "detail": path},
    }


def build_fields(event_type: str, limits: Limits, fields: Mapping[str, Any]) -> dict[str, Any]:
    """The type-specific fields of an event, validated and cleaned; raises `ValueError` if wrong."""
    cleaners = _cleaners(limits).get(event_type)
    if cleaners is None:
        raise ValueError(f"{event_type!r} is not an event type a service can log")
    missing = set(cleaners) - set(fields)
    if missing:
        raise ValueError(f"{event_type} is missing {', '.join(sorted(missing))}")
    unexpected = set(fields) - set(cleaners)
    if unexpected:
        raise ValueError(f"{event_type} has unexpected fields {', '.join(sorted(unexpected))}")
    cleaned: dict[str, Any] = {}
    for name, clean in cleaners.items():
        try:
            cleaned[name] = clean(fields[name])
        except ValueError as error:
            raise ValueError(f"{name}: {error}") from error
    return cleaned
