"""One session's JSONL log: the records, the caps, and the aggregation that keeps a flood bounded.

Every event goes through `SessionLog.record`, which decides whether it is written in full or only
counted (see `SCHEMA.md` for the policy). Nothing here raises into a service: a log that cannot be
written loses events and counts the failures, it never takes a connection down.
"""

import json
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from lan_sim.clock import Clock
from lan_sim.events import ELLIPSIS, Endpoint, build_fields
from lan_sim.limits import Limits

REFUSED_SOURCE_LIMIT = "connections-per-source-service"
REFUSED_SESSION_LIMIT = "connections-per-session"
REFUSED_FOREIGN_HOST = "host-not-in-session"
REFUSED_PORT_NOT_SERVED = "port-not-served"


class LineSink(Protocol):
    def write_line(self, line: str) -> None: ...

    def close(self) -> None: ...


class FileSink:
    """Appends to a file, opened on the first line so a session that logs nothing leaves no file."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._handle: Any = None

    def write_line(self, line: str) -> None:
        if self._handle is None:
            self._handle = open(self._path, "a", encoding="ascii", newline="\n")  # noqa: SIM115
        self._handle.write(line + "\n")
        self._handle.flush()

    def close(self) -> None:
        if self._handle is not None:
            self._handle.close()
            self._handle = None


def _shorten(text: str, max_length: int) -> str:
    return text if len(text) <= max_length else text[: max_length - 1] + ELLIPSIS


def _timestamp(moment: Any) -> str:
    return moment.isoformat(timespec="milliseconds").replace("+00:00", "Z")


@dataclass
class Aggregate:
    """What was collapsed for one (host, service): the events past its full-event cap."""

    count: int = 0
    first_time: str = ""
    last_time: str = ""
    by_type: Counter[str] = field(default_factory=Counter)
    users: list[str] = field(default_factory=list)
    secrets: list[str] = field(default_factory=list)

    def add(self, event_type: str, body: dict[str, Any], time: str, limits: Limits) -> None:
        self.count += 1
        self.first_time = self.first_time or time
        self.last_time = time
        self.by_type[event_type] += 1
        self._remember(
            self.users,
            body.get("user"),
            limits.max_aggregate_usernames,
            limits.max_aggregate_username_length,
        )
        self._remember(
            self.secrets,
            body.get("secret"),
            limits.max_aggregate_secrets,
            limits.max_aggregate_secret_length,
        )

    @staticmethod
    def _remember(kept: list[str], value: Any, capacity: int, max_length: int) -> None:
        if value is None or len(kept) >= capacity:
            return
        shortened = _shorten(value, max_length)
        if shortened not in kept:
            kept.append(shortened)

    def record(self, host: str, service: str) -> dict[str, Any]:
        return {
            "host": host,
            "service": service,
            "count": self.count,
            "first_time": self.first_time,
            "last_time": self.last_time,
            "by_type": dict(self.by_type),
            "users": self.users,
            "secrets": self.secrets,
        }


@dataclass(frozen=True)
class _Event:
    type: str
    host: str
    service: str
    src: Endpoint
    dst: Endpoint
    body: dict[str, Any]
    time: str

    @property
    def pair(self) -> tuple[str, str]:
        return (self.host, self.service)

    def document(self) -> dict[str, Any]:
        return {
            "time": self.time,
            "type": self.type,
            "host": self.host,
            "service": self.service,
            "src": {"ip": self.src.ip, "port": self.src.port},
            "dst": {"ip": self.dst.ip, "port": self.dst.port},
            **self.body,
        }


class SessionLog:
    def __init__(self, key: str, sink: LineSink, clock: Clock, limits: Limits) -> None:
        self._key = key
        self._sink = sink
        self._clock = clock
        self._limits = limits
        self._written_by_service: Counter[tuple[str, str]] = Counter()
        self._aggregates: dict[tuple[str, str], Aggregate] = {}
        self._events_by_type: Counter[str] = Counter()
        self._refused: Counter[str] = Counter()
        self._events_logged = 0
        self._bytes_logged = 0
        self._connections = 0
        self._bytes_in = 0
        self._bytes_out = 0
        self._aggregated = 0
        self._rate_limited = 0
        self._hard_capped = 0
        self._write_errors = 0
        self._truncated = False
        self._closed = False
        self._rate_window = -1
        self._rate_count = 0

    def connection_log(
        self, host: str, service: str, src: Endpoint, dst: Endpoint
    ) -> "ConnectionLog":
        return ConnectionLog(self, host, service, src, dst)

    def count_refused(self, reason: str) -> None:
        self._refused[reason] += 1

    def record(
        self,
        event_type: str,
        *,
        host: str,
        service: str,
        src: Endpoint,
        dst: Endpoint,
        **fields: Any,
    ) -> bool:
        """Logs the event in full if the caps allow, else only counts it; True if written."""
        if self._closed:
            return False
        body = build_fields(event_type, self._limits, fields)
        self._events_by_type[event_type] += 1
        if event_type == "connection":
            self._connections += 1
            self._bytes_in += body["bytes_in"]
            self._bytes_out += body["bytes_out"]
        event = _Event(event_type, host, service, src, dst, body, _timestamp(self._clock.now()))
        if self._write_if_allowed(event):
            return True
        aggregate = self._aggregates.setdefault((host, service), Aggregate())
        aggregate.add(event_type, body, event.time, self._limits)
        return False

    def _write_if_allowed(self, event: _Event) -> bool:
        if self._truncated or self._events_logged >= self._limits.max_events_per_session:
            self._truncated = True
            self._hard_capped += 1
            return False
        if self._written_by_service[event.pair] >= self._limits.full_events_per_service:
            self._aggregated += 1
            return False
        if not self._rate_allows():
            self._rate_limited += 1
            return False
        line = self._line(event.document())
        if self._bytes_logged + len(line) + 1 > self._limits.max_log_bytes_per_session:
            self._truncated = True
            self._hard_capped += 1
            return False
        if not self._write(line):
            return False
        self._events_logged += 1
        self._written_by_service[event.pair] += 1
        return True

    def _rate_allows(self) -> bool:
        window = int(self._clock.monotonic())
        if window != self._rate_window:
            self._rate_window = window
            self._rate_count = 0
        if self._rate_count >= self._limits.max_events_per_second:
            return False
        self._rate_count += 1
        return True

    @staticmethod
    def _line(document: dict[str, Any]) -> str:
        return json.dumps(document, separators=(",", ":"))

    def _write(self, line: str) -> bool:
        try:
            self._sink.write_line(line)
        except OSError:
            self._write_errors += 1
            return False
        self._bytes_logged += len(line) + 1
        return True

    def close(self) -> None:
        """Writes the aggregates and the final record, which are not subject to the caps."""
        if self._closed:
            return
        self._closed = True
        time = _timestamp(self._clock.now())
        for (host, service), aggregate in sorted(self._aggregates.items()):
            self._write(
                self._line({"time": time, "type": "aggregate", **aggregate.record(host, service)})
            )
        self._write(
            self._line(
                {
                    "time": time,
                    "type": "session-end",
                    "session": self._key,
                    "log_truncated": self._truncated,
                    "counters": self._counters(),
                }
            )
        )
        try:
            self._sink.close()
        except OSError:
            self._write_errors += 1

    def _counters(self) -> dict[str, Any]:
        return {
            "connections": self._connections,
            "bytes_in": self._bytes_in,
            "bytes_out": self._bytes_out,
            "events_logged": self._events_logged,
            "events_by_type": dict(self._events_by_type),
            "events_aggregated": self._aggregated,
            "events_rate_limited": self._rate_limited,
            "events_hard_capped": self._hard_capped,
            "write_errors": self._write_errors,
            "refused": dict(self._refused),
        }


class ConnectionLog:
    """The logging methods a connection's service calls, with host, service and endpoints bound."""

    def __init__(
        self, log: SessionLog, host: str, service: str, src: Endpoint, dst: Endpoint
    ) -> None:
        self._log = log
        self._where = {"host": host, "service": service, "src": src, "dst": dst}

    def login_attempt(
        self, *, user: str, domain: str, mechanism: str, secret: str, success: bool
    ) -> bool:
        return self._log.record(
            "login-attempt",
            **self._where,
            user=user,
            domain=domain,
            mechanism=mechanism,
            secret=secret,
            success=success,
        )

    def share_access(self, *, share: str, path: str, operation: str) -> bool:
        return self._log.record(
            "share-access", **self._where, share=share, path=path, operation=operation
        )

    def file_write(self, *, share: str, path: str, size: int, sha256: str, truncated: bool) -> bool:
        return self._log.record(
            "file-write",
            **self._where,
            share=share,
            path=path,
            size=size,
            sha256=sha256,
            truncated=truncated,
        )

    def service_request(self, *, name: str, detail: str) -> bool:
        return self._log.record("service-request", **self._where, name=name, detail=detail)

    def connection(self, *, bytes_in: int, bytes_out: int, duration_ms: int) -> bool:
        return self._log.record(
            "connection",
            **self._where,
            bytes_in=bytes_in,
            bytes_out=bytes_out,
            duration_ms=duration_ms,
        )
