"""Reads the fake-LAN daemon's event log (`lansim/events.jsonl`, schema in `lan-sim/SCHEMA.md`).

The daemon is sandboxed but every string in its log came from malware talking to a fake host, so
the file is read as hostile: lines and the whole file are size-bounded, a record that is not
exactly what the schema says is skipped (never raised on), and every string is cleaned and cut
again here whatever the daemon already did to it.
"""

import ipaddress
import json
import re
import unicodedata
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, BinaryIO

from app.ingest.ecs import ELLIPSIS, format_timestamp

LOG = ("lansim", "events.jsonl")
MAX_LINE_BYTES = 64 * 1024
MAX_LOG_BYTES = 16 * 1024 * 1024
REPLACEMENT = "\ufffd"
SURROGATE = "Cs"
DROPPED_CATEGORIES = frozenset({"Cc", "Cf", "Co", "Cn", "Zl", "Zp"})
MAX_COUNT = 2**63 - 1
MAX_PORT = 65535
MAX_AGGREGATE_USERS = 50
MAX_AGGREGATE_SECRETS = 5
MAX_NAMED_COUNTS = 16
MAX_TIME_TEXT = 64
SHA256 = re.compile(r"[0-9a-f]{64}")

CONNECTION = "connection"
SESSION_END = "session-end"
type Reader = Callable[[Any], Any]


class _InvalidError(ValueError):
    """The record is not what the schema says; it is skipped."""


@dataclass(frozen=True)
class Endpoint:
    ip: str
    port: int


@dataclass(frozen=True)
class LogRecord:
    """One event of the log, validated. `index` is its line number, so ids do not move when a
    neighbouring line is skipped; `fields` are the type's own fields (`SCHEMA.md`), cleaned.
    """

    index: int
    time: datetime
    type: str
    host: str
    service: str
    source: Endpoint | None
    destination: Endpoint | None
    fields: Mapping[str, Any]
    raw: Mapping[str, Any]


@dataclass(frozen=True)
class SessionEnd:
    log_truncated: bool
    counters: Mapping[str, int]


@dataclass(frozen=True)
class LanLog:
    records: list[LogRecord]
    session_end: SessionEnd | None


def clean_text(value: str, limit: int) -> str:
    """The printable part of `value`, at most `limit` characters; a final ellipsis marks a cut."""
    # Only the head is scanned, so a 10 MB string costs no more than a short one.
    cleaned = "".join(_clean_character(character) for character in value[: limit + 1])
    return cleaned[: limit - 1] + ELLIPSIS if len(value) > limit else cleaned[:limit]


def _clean_character(character: str) -> str:
    category = unicodedata.category(character)
    if category == SURROGATE:
        return REPLACEMENT
    return "" if category in DROPPED_CATEGORIES else character


def _text(limit: int) -> Reader:
    def read(value: Any) -> str:
        if not isinstance(value, str):
            raise _InvalidError("not a string")
        return clean_text(value, limit)

    return read


def _texts(limit: int, count: int) -> Reader:
    read_one = _text(limit)

    def read(value: Any) -> list[str]:
        if not isinstance(value, list):
            raise _InvalidError("not a list")
        return [read_one(item) for item in value[:count]]

    return read


def _count(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise _InvalidError("not a count")
    return min(value, MAX_COUNT)


def _counts_by_name(value: Any) -> dict[str, int]:
    if not isinstance(value, dict):
        raise _InvalidError("not an object")
    return {
        _text(MAX_TIME_TEXT)(name): _count(count)
        for name, count in list(value.items())[:MAX_NAMED_COUNTS]
    }


def _flag(value: Any) -> bool:
    if not isinstance(value, bool):
        raise _InvalidError("not a flag")
    return value


def _sha256(value: Any) -> str:
    if not isinstance(value, str) or not SHA256.fullmatch(value):
        raise _InvalidError("not a SHA-256")
    return value


def _time(value: Any) -> datetime:
    if not isinstance(value, str) or len(value) > MAX_TIME_TEXT:
        raise _InvalidError("not a time")
    try:
        moment = datetime.fromisoformat(value)
    except ValueError:
        raise _InvalidError("not a time") from None
    if moment.tzinfo is None:
        raise _InvalidError("a time needs its zone")
    return moment.astimezone(UTC)


def _endpoint(value: Any) -> Endpoint:
    if not isinstance(value, dict):
        raise _InvalidError("not an endpoint")
    port = value.get("port")
    if isinstance(port, bool) or not isinstance(port, int) or not 0 <= port <= MAX_PORT:
        raise _InvalidError("not a port")
    try:
        address = ipaddress.ip_address(value.get("ip"))  # type: ignore[arg-type]
    except ValueError:
        raise _InvalidError("not an address") from None
    return Endpoint(str(address), port)


_REQUIRED: Any = object()
_TEXT_256, _TEXT_1024 = _text(256), _text(1024)

# type -> field -> (reader, value when the record leaves the field out)
_FIELDS: dict[str, dict[str, tuple[Reader, Any]]] = {
    "login-attempt": {
        "user": (_TEXT_256, ""),
        "domain": (_TEXT_256, ""),
        "mechanism": (_text(32), ""),
        "secret": (_text(4096), ""),
        "success": (_flag, _REQUIRED),
    },
    "share-access": {
        "share": (_TEXT_256, ""),
        "path": (_TEXT_1024, ""),
        "operation": (_TEXT_256, ""),
    },
    "file-write": {
        "share": (_TEXT_256, ""),
        "path": (_TEXT_1024, ""),
        "size": (_count, _REQUIRED),
        "sha256": (_sha256, ""),
        "truncated": (_flag, False),
    },
    "service-request": {"name": (_TEXT_256, ""), "detail": (_TEXT_1024, "")},
    "aggregate": {
        "count": (_count, _REQUIRED),
        "first_time": (_time, None),
        "last_time": (_time, None),
        "by_type": (_counts_by_name, {}),
        "users": (_texts(64, MAX_AGGREGATE_USERS), []),
        "secrets": (_texts(1024, MAX_AGGREGATE_SECRETS), []),
    },
}
_WITH_ENDPOINTS = frozenset({"login-attempt", "share-access", "file-write", "service-request"})


def read_lan_log(path: Path) -> LanLog:
    """The log's events in file order; a missing or unreadable file is an empty log, a truncated
    one gives what it holds, and a line that is not a valid record is skipped.
    """
    try:
        handle = path.open("rb")
    except OSError:
        return LanLog([], None)
    records: list[LogRecord] = []
    session_end: SessionEnd | None = None
    with handle:
        for index, line in enumerate(_lines(handle)):
            parsed = None if line is None else _parse(index, line)
            if isinstance(parsed, LogRecord):
                records.append(parsed)
            elif parsed is not None:
                session_end = _merged(session_end, parsed)
    return LanLog(records, session_end)


def _merged(earlier: SessionEnd | None, later: SessionEnd) -> SessionEnd:
    """A session reopened under one key ends twice; the log was truncated if either end says so."""
    truncated = later.log_truncated or (earlier is not None and earlier.log_truncated)
    return SessionEnd(truncated, later.counters)


def _lines(handle: BinaryIO) -> Iterator[bytes | None]:
    """Each line; `None` for one over the line limit, so it keeps its place in the numbering."""
    consumed = 0
    while consumed < MAX_LOG_BYTES:
        line = handle.readline(MAX_LINE_BYTES + 1)
        if not line:
            return
        consumed += len(line)
        if len(line) > MAX_LINE_BYTES and not line.endswith(b"\n"):
            consumed += _skip_rest_of_line(handle)
            yield None
        else:
            yield line


def _skip_rest_of_line(handle: BinaryIO) -> int:
    skipped = 0
    while chunk := handle.readline(MAX_LINE_BYTES):
        skipped += len(chunk)
        if chunk.endswith(b"\n"):
            break
    return skipped


def _parse(index: int, line: bytes) -> LogRecord | SessionEnd | None:
    try:
        body = json.loads(line.decode("utf-8", errors="replace"), parse_constant=_reject_constant)
        if not isinstance(body, dict):
            return None
        kind = body.get("type")
        if kind == SESSION_END:
            return _session_end(body)
        if kind in _FIELDS:
            return _record(index, kind, body)
    except (ValueError, RecursionError):
        pass
    return None


def _reject_constant(name: str) -> object:
    raise ValueError(f"{name} is not valid JSON")


def _session_end(body: dict[str, Any]) -> SessionEnd:
    counters = body.get("counters")
    named = counters.items() if isinstance(counters, dict) else ()
    return SessionEnd(
        _flag(body.get("log_truncated", False)),
        {
            _text(MAX_TIME_TEXT)(name): value
            for name, value in list(named)[: MAX_NAMED_COUNTS * 4]
            if isinstance(name, str) and isinstance(value, int) and not isinstance(value, bool)
        },
    )


def _record(index: int, kind: str, body: dict[str, Any]) -> LogRecord:
    moment = _time(body.get("time"))
    host, service = _text(256)(body.get("host")), _text(32)(body.get("service"))
    with_endpoints = kind in _WITH_ENDPOINTS
    source = _endpoint(body.get("src")) if with_endpoints else None
    destination = _endpoint(body.get("dst")) if with_endpoints else None
    fields = {name: _field(body, name, *spec) for name, spec in _FIELDS[kind].items()}
    raw: dict[str, Any] = {"time": format_timestamp(moment), "type": kind, "host": host}
    raw["service"] = service
    if source and destination:
        raw["src"], raw["dst"] = vars(source), vars(destination)
    raw |= {name: _jsonable(value) for name, value in fields.items()}
    return LogRecord(index, moment, kind, host, service, source, destination, fields, raw)


def _field(body: dict[str, Any], name: str, reader: Reader, default: Any) -> Any:
    if name not in body:
        if default is _REQUIRED:
            raise _InvalidError(f"{name} is missing")
        return default
    return reader(body[name])


def _jsonable(value: Any) -> Any:
    return format_timestamp(value) if isinstance(value, datetime) else value
