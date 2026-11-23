"""Records of the fake-LAN daemon's log (`lan-sim/SCHEMA.md`) and the analysis around them."""

import json
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from app.ingest.protocol import IngestContext, LanHost

ANALYSIS_ID = 6
STARTED = datetime(2026, 11, 23, 12, 0, 0, tzinfo=UTC)
GUEST = "192.168.150.10"
PRESET = "small-office"
FILE_SERVER = "192.168.150.201"
DOMAIN_CONTROLLER = "192.168.150.200"

LAN_HOSTS: dict[str, LanHost] = {
    DOMAIN_CONTROLLER: LanHost(
        "dc01.corp.local", "domain-controller", PRESET, {445: "smb", 389: "ldap"}
    ),
    FILE_SERVER: LanHost("fs01.corp.local", "file-server", PRESET, {445: "smb", 3389: "rdp"}),
    **{
        f"192.168.150.{last}": LanHost(
            f"ws{last}.corp.local", "workstation", PRESET, {445: "smb", 3389: "rdp", 5985: "winrm"}
        )
        for last in range(202, 210)
    },
}


def stamp(moment: datetime) -> str:
    return moment.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def at(seconds: float) -> datetime:
    return STARTED + timedelta(seconds=seconds)


def address_of(fqdn: str | None) -> str:
    return next((a for a, host in LAN_HOSTS.items() if host.fqdn == fqdn), FILE_SERVER)


def record(  # noqa: PLR0913 - the endpoints of a record, each a field a test varies
    kind: str,
    *,
    seconds: float = 1,
    host: str = "fs01.corp.local",
    service: str = "smb",
    port: int = 445,
    source_port: int = 50123,
    **fields: Any,
) -> dict[str, Any]:
    """A connection-bearing record; a field given as None is left out."""
    body = {
        "time": stamp(at(seconds)),
        "type": kind,
        "host": host,
        "service": service,
        "src": {"ip": GUEST, "port": source_port},
        "dst": {"ip": address_of(host), "port": port},
        **fields,
    }
    return {name: value for name, value in body.items() if value is not None}


def login(**fields: Any) -> dict[str, Any]:
    defaults = {
        "user": "Administrator",
        "domain": "CORP",
        "mechanism": "ntlm",
        "secret": "Password1",
        "success": False,
    }
    return record("login-attempt", **defaults | fields)


def share_access(**fields: Any) -> dict[str, Any]:
    defaults = {"share": "ADMIN$", "path": "\\x.txt", "operation": "open"}
    return record("share-access", **defaults | fields)


def file_write(**fields: Any) -> dict[str, Any]:
    defaults = {
        "share": "ADMIN$",
        "path": "\\evil.exe",
        "size": 61440,
        "sha256": "ab" * 32,
        "truncated": False,
    }
    return record("file-write", **defaults | fields)


def service_request(**fields: Any) -> dict[str, Any]:
    defaults = {"name": "svcctl CreateService", "detail": "evil, C:\\Windows\\evil.exe"}
    return record("service-request", **defaults | fields)


def aggregate(**fields: Any) -> dict[str, Any]:
    return {
        "time": stamp(at(300)),
        "type": "aggregate",
        "host": "fs01.corp.local",
        "service": "smb",
        "count": 9800,
        "first_time": stamp(at(2)),
        "last_time": stamp(at(298)),
        "by_type": {"connection": 4900, "login-attempt": 4900},
        "users": ["admin", "root"],
        "secrets": ["Password1"],
        **fields,
    }


def session_end(*, log_truncated: bool = False) -> dict[str, Any]:
    return {
        "time": stamp(at(301)),
        "type": "session-end",
        "session": "analysis-6",
        "log_truncated": log_truncated,
        "counters": {"connections": 3, "events_logged": 3, "events_hard_capped": 0},
    }


def log_lines(records: Iterable[Mapping[str, Any] | str | bytes]) -> bytes:
    """The log's bytes, one record a line; a string or bytes is written as the line itself."""
    lines = [
        item
        if isinstance(item, bytes)
        else (item if isinstance(item, str) else json.dumps(item)).encode()
        for item in records
    ]
    return b"\n".join(lines) + b"\n"


def write_log(analysis_dir: Path, records: Iterable[Mapping[str, Any] | str | bytes]) -> Path:
    path = analysis_dir / "lansim" / "events.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(log_lines(records))
    return path


def context_of(
    analysis_dir: Path | None, lan_hosts: Mapping[str, LanHost] | None = None
) -> IngestContext:
    return IngestContext(
        ANALYSIS_ID,
        STARTED,
        analysis_dir=analysis_dir,
        lan_hosts=LAN_HOSTS if lan_hosts is None else lan_hosts,
    )
