"""The wire contract between the LAN control service and the `lan-sim` daemon.

The control service and the daemon run in different containers that share one directory. This file
is the only place that directory's layout and file formats are written down, so it ships into both
images and uses the standard library only (the precedent is `machine_broker_client.py`).

    <root>/sessions/<key>.json   written by the control service, read by the daemon
    <root>/status/<key>.json     written by the daemon
    <root>/logs/<key>.jsonl      written by the daemon (its schema is `lan-sim/SCHEMA.md`)

Open: the control service calls `publish_session`, then `wait_for_status(..., {"listening",
"failed"})`. The daemon writes `listening` only after every listener of the session is bound, and
`failed` (with the reason, and nothing bound for that session) otherwise.

Close: the control service calls `retract_session`. The daemon notices (it polls), closes that
session's listeners, appends the final `session-end` record to the log and writes `closed`.

Every file is written atomically (`atomic_write`), so a reader sees the old or the new content,
never half of it. Session files are validated strictly on both sides: unknown fields, oversized
files and malformed values are refused, because the daemon binds sockets from what they say.
"""

import ipaddress
import json
import math
import os
import re
import tempfile
import time
from collections.abc import Callable, Collection, Iterable, Mapping
from contextlib import suppress
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

DEFAULT_ROOT = "/run/lan-sim"

KEY = re.compile(r"[A-Za-z0-9][A-Za-z0-9-]{0,63}")
PRESET_ID = re.compile(r"[a-z][a-z0-9-]{1,31}")
SERVICE_KIND = re.compile(r"[a-z][a-z0-9-]{0,31}")
DNS_LABEL = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?")

STATES = ("listening", "failed", "closed")

MAX_SESSION_FILE_BYTES = 256 * 1024
MAX_STATUS_FILE_BYTES = 8 * 1024
MAX_HOSTS = 48
MAX_SERVICES_PER_HOST = 16
MAX_ACCOUNTS_PER_HOST = 16
MAX_FQDN_LENGTH = 253
MAX_BANNER_LENGTH = 200
MAX_CREDENTIAL_LENGTH = 256
MAX_ERROR_LENGTH = 500
MAX_OPTION_DEPTH = 4
MAX_OPTION_NAME_LENGTH = 64
MAX_OPTION_STRING_LENGTH = 1024

DEFAULT_POLL_INTERVAL_S = 0.05
FIRST_PRINTABLE = 0x20
DELETE = 0x7F
MAX_PORT = 65535
MIN_FQDN_LABELS = 2


class SessionFormatError(ValueError):
    """A session or status file, or a key, that the contract does not allow."""


def checked_key(key: object) -> str:
    if not isinstance(key, str) or not KEY.fullmatch(key):
        raise SessionFormatError(
            "key must be 1 to 64 letters, digits or dashes, not starting with a dash"
        )
    return key


def _has_control_character(text: str) -> bool:
    return any(ord(character) < FIRST_PRINTABLE or ord(character) == DELETE for character in text)


def _text(value: object, name: str, *, max_length: int, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise SessionFormatError(f"{name} must be a string")
    if len(value) > max_length:
        raise SessionFormatError(f"{name} is longer than {max_length} characters")
    if not value and not allow_empty:
        raise SessionFormatError(f"{name} must not be empty")
    if _has_control_character(value):
        raise SessionFormatError(f"{name} must not contain control characters")
    return value


def _pattern(value: object, name: str, pattern: re.Pattern[str]) -> str:
    if not isinstance(value, str) or not pattern.fullmatch(value):
        raise SessionFormatError(f"{name} is not valid: {pattern.pattern}")
    return value


def _unicast_address(value: object, name: str) -> str:
    try:
        address = ipaddress.IPv4Address(value) if isinstance(value, str) else None
    except ValueError:
        address = None
    if address is None or str(address) != value:
        raise SessionFormatError(f"{name} must be a dotted IPv4 address")
    if (
        address.is_unspecified
        or address.is_multicast
        or address == ipaddress.IPv4Address("255.255.255.255")
    ):
        raise SessionFormatError(f"{name} must be a unicast address, not {value}")
    return str(address)


def _port(value: object) -> int:
    if type(value) is not int or not 1 <= value <= MAX_PORT:
        raise SessionFormatError("port must be an integer from 1 to 65535")
    return value


def _fqdn(value: object) -> str:
    if not isinstance(value, str) or len(value) > MAX_FQDN_LENGTH:
        raise SessionFormatError(f"fqdn must be a name of at most {MAX_FQDN_LENGTH} characters")
    labels = value.split(".")
    if len(labels) < MIN_FQDN_LABELS or not all(DNS_LABEL.fullmatch(label) for label in labels):
        raise SessionFormatError(
            f"fqdn must be two or more lowercase DNS labels, not {value[:80]!r}"
        )
    return value


def _option_value(value: object, depth: int) -> Any:
    if value is None or isinstance(value, bool | int):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise SessionFormatError("options must not contain a non-finite number")
        return value
    if isinstance(value, str):
        return _text(
            value, "an option string", max_length=MAX_OPTION_STRING_LENGTH, allow_empty=True
        )
    if depth >= MAX_OPTION_DEPTH:
        raise SessionFormatError(f"options are nested deeper than {MAX_OPTION_DEPTH} levels")
    if isinstance(value, list | tuple):
        return [_option_value(item, depth + 1) for item in value]
    if isinstance(value, Mapping):
        return _options_mapping(value, depth + 1)
    raise SessionFormatError(f"options must hold JSON values, not {type(value).__name__}")


def _options_mapping(value: Mapping[Any, Any], depth: int) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for name, item in value.items():
        checked = _text(name, "an option name", max_length=MAX_OPTION_NAME_LENGTH)
        result[checked] = _option_value(item, depth)
    return result


def _options(value: object) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise SessionFormatError("options must be an object")
    return _options_mapping(value, 1)


@dataclass(frozen=True)
class ServiceSpec:
    kind: str
    port: int
    options: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _pattern(self.kind, "kind", SERVICE_KIND)
        _port(self.port)
        object.__setattr__(self, "options", _options(self.options))


@dataclass(frozen=True)
class HostSpec:
    fqdn: str
    address: str
    os_banner: str
    accounts: tuple[tuple[str, str], ...]
    services: tuple[ServiceSpec, ...]

    def __post_init__(self) -> None:
        _fqdn(self.fqdn)
        _unicast_address(self.address, "address")
        _text(self.os_banner, "os_banner", max_length=MAX_BANNER_LENGTH, allow_empty=True)
        accounts = tuple(self.accounts)
        if len(accounts) > MAX_ACCOUNTS_PER_HOST:
            raise SessionFormatError(f"accounts has more than {MAX_ACCOUNTS_PER_HOST} entries")
        for user, password in accounts:
            _text(user, "user", max_length=MAX_CREDENTIAL_LENGTH)
            _text(password, "password", max_length=MAX_CREDENTIAL_LENGTH, allow_empty=True)
        services = tuple(self.services)
        if len(services) > MAX_SERVICES_PER_HOST:
            raise SessionFormatError(f"services has more than {MAX_SERVICES_PER_HOST} entries")
        ports = [service.port for service in services]
        if len(set(ports)) != len(ports):
            raise SessionFormatError(f"{self.fqdn} lists a port twice")
        object.__setattr__(self, "accounts", accounts)
        object.__setattr__(self, "services", services)

    def service_on(self, port: int) -> ServiceSpec | None:
        return next((service for service in self.services if service.port == port), None)


@dataclass(frozen=True)
class SessionSpec:
    key: str
    guest_address: str
    preset_id: str
    hosts: tuple[HostSpec, ...]

    def __post_init__(self) -> None:
        checked_key(self.key)
        _unicast_address(self.guest_address, "guest_address")
        _pattern(self.preset_id, "preset_id", PRESET_ID)
        hosts = tuple(self.hosts)
        if not 1 <= len(hosts) <= MAX_HOSTS:
            raise SessionFormatError(f"hosts must hold 1 to {MAX_HOSTS} entries")
        for name, values in (
            ("address", [host.address for host in hosts]),
            ("fqdn", [host.fqdn for host in hosts]),
        ):
            if len(set(values)) != len(values):
                raise SessionFormatError(f"two hosts share an {name}")
        if self.guest_address in {host.address for host in hosts}:
            raise SessionFormatError("guest_address is also the address of a host")
        object.__setattr__(self, "hosts", hosts)

    def host_at(self, address: str) -> HostSpec | None:
        return next((host for host in self.hosts if host.address == address), None)

    def endpoints(self) -> list[tuple[str, int]]:
        """Every (host address, service port) this session needs a listener for."""
        return [(host.address, service.port) for host in self.hosts for service in host.services]

    def to_json(self) -> str:
        return json.dumps(
            {
                "key": self.key,
                "guest_address": self.guest_address,
                "preset_id": self.preset_id,
                "hosts": [_host_document(host) for host in self.hosts],
            },
            separators=(",", ":"),
        )

    @classmethod
    def from_json(cls, raw: str | bytes) -> "SessionSpec":
        document = _parse_object(raw, MAX_SESSION_FILE_BYTES, "session file")
        _exact_fields(document, ("key", "guest_address", "preset_id", "hosts"), "session")
        hosts = _list(document["hosts"], "hosts")
        return cls(
            key=document["key"],
            guest_address=document["guest_address"],
            preset_id=document["preset_id"],
            hosts=tuple(_host_from_document(host) for host in hosts[: MAX_HOSTS + 1]),
        )


def _host_document(host: HostSpec) -> dict[str, Any]:
    return {
        "fqdn": host.fqdn,
        "address": host.address,
        "os_banner": host.os_banner,
        "accounts": [{"user": user, "password": password} for user, password in host.accounts],
        "services": [
            {"kind": service.kind, "port": service.port, "options": service.options}
            for service in host.services
        ],
    }


def _host_from_document(document: object) -> HostSpec:
    host = _object(document, "host")
    _exact_fields(host, ("fqdn", "address", "os_banner", "accounts", "services"), "host")
    accounts = _list(host["accounts"], "accounts")
    services = _list(host["services"], "services")
    if len(accounts) > MAX_ACCOUNTS_PER_HOST:
        raise SessionFormatError(f"accounts has more than {MAX_ACCOUNTS_PER_HOST} entries")
    if len(services) > MAX_SERVICES_PER_HOST:
        raise SessionFormatError(f"services has more than {MAX_SERVICES_PER_HOST} entries")
    return HostSpec(
        fqdn=host["fqdn"],
        address=host["address"],
        os_banner=host["os_banner"],
        accounts=tuple(_account_from_document(account) for account in accounts),
        services=tuple(_service_from_document(service) for service in services),
    )


def _account_from_document(document: object) -> tuple[str, str]:
    account = _object(document, "account")
    _exact_fields(account, ("user", "password"), "account")
    return account["user"], account["password"]


def _service_from_document(document: object) -> ServiceSpec:
    service = _object(document, "service")
    _exact_fields(service, ("kind", "port", "options"), "service")
    return ServiceSpec(kind=service["kind"], port=service["port"], options=service["options"])


def _object(value: object, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise SessionFormatError(f"{name} must be an object")
    return value


def _list(value: object, name: str) -> list[Any]:
    if not isinstance(value, list):
        raise SessionFormatError(f"{name} must be a list")
    return value


def _exact_fields(document: Mapping[str, Any], names: Iterable[str], where: str) -> None:
    expected = set(names)
    for name in sorted(set(document) - expected):
        raise SessionFormatError(f"{where}: unknown field {name!r}")
    for name in sorted(expected - set(document)):
        raise SessionFormatError(f"{where}: missing field {name!r}")


def _reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for name, value in pairs:
        if name in result:
            raise ValueError(f"duplicate field {name!r}")
        result[name] = value
    return result


def _reject_constant(name: str) -> Any:
    raise ValueError(f"{name} is not a JSON number")


def _parse_object(raw: str | bytes, max_bytes: int, what: str) -> dict[str, Any]:
    if len(raw) > max_bytes:
        raise SessionFormatError(f"{what} is too large (over {max_bytes} bytes)")
    try:
        text = raw.decode("utf-8") if isinstance(raw, bytes) else raw
        document = json.loads(
            text, object_pairs_hook=_reject_duplicates, parse_constant=_reject_constant
        )
    except RecursionError as error:
        raise SessionFormatError(f"{what} is nested too deeply") from error
    except ValueError as error:
        raise SessionFormatError(f"{what} is not valid JSON: {error}") from error
    if not isinstance(document, dict):
        raise SessionFormatError(f"{what} must be a JSON object")
    return document


@dataclass(frozen=True)
class SessionStatus:
    state: str
    error: str | None = None

    def __post_init__(self) -> None:
        if self.state not in STATES:
            raise SessionFormatError(f"state must be one of {', '.join(STATES)}")
        if self.state == "failed":
            if not isinstance(self.error, str) or not self.error:
                raise SessionFormatError("a failed status needs an error saying why")
            cleaned = "".join(
                " " if _has_control_character(character) else character for character in self.error
            )
            object.__setattr__(self, "error", cleaned[:MAX_ERROR_LENGTH])
        elif self.error is not None:
            raise SessionFormatError(f"a {self.state} status carries no error")

    def to_json(self) -> str:
        return json.dumps({"state": self.state, "error": self.error}, separators=(",", ":"))

    @classmethod
    def from_json(cls, raw: str | bytes) -> "SessionStatus":
        document = _parse_object(raw, MAX_STATUS_FILE_BYTES, "status file")
        _exact_fields(document, ("state", "error"), "status")
        return cls(state=document["state"], error=document["error"])


@dataclass(frozen=True)
class Layout:
    root: Path = Path(DEFAULT_ROOT)

    def __post_init__(self) -> None:
        object.__setattr__(self, "root", Path(self.root))

    @property
    def sessions_dir(self) -> Path:
        return self.root / "sessions"

    @property
    def status_dir(self) -> Path:
        return self.root / "status"

    @property
    def logs_dir(self) -> Path:
        return self.root / "logs"

    def session_file(self, key: str) -> Path:
        return self.sessions_dir / f"{checked_key(key)}.json"

    def status_file(self, key: str) -> Path:
        return self.status_dir / f"{checked_key(key)}.json"

    def log_file(self, key: str) -> Path:
        return self.logs_dir / f"{checked_key(key)}.jsonl"

    def make_directories(self) -> None:
        for directory in (self.sessions_dir, self.status_dir, self.logs_dir):
            directory.mkdir(parents=True, exist_ok=True)


def atomic_write(path: Path, data: str | bytes) -> None:
    """Replaces `path` with `data` in one step; the temporary name never ends in `.json`."""
    content = data.encode() if isinstance(data, str) else data
    descriptor, temporary = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.name}.", suffix=".tmp"
    )
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o644)
        os.replace(temporary, path)
    except BaseException:
        with suppress(OSError):
            os.unlink(temporary)
        raise


def _read_bounded(path: Path, max_bytes: int, what: str, *, follow_symlinks: bool) -> bytes:
    flags = os.O_RDONLY | (0 if follow_symlinks else os.O_NOFOLLOW)
    with os.fdopen(os.open(path, flags), "rb") as handle:
        raw = handle.read(max_bytes + 1)
    if len(raw) > max_bytes:
        raise SessionFormatError(f"{what} is too large (over {max_bytes} bytes)")
    return raw


def publish_session(layout: Layout, spec: SessionSpec) -> None:
    layout.sessions_dir.mkdir(parents=True, exist_ok=True)
    # A status left by an earlier session of the same key would answer wait_for_status at once.
    # Best effort: the control service may not own the daemon's status directory.
    with suppress(OSError):
        layout.status_file(spec.key).unlink(missing_ok=True)
    atomic_write(layout.session_file(spec.key), spec.to_json())


def retract_session(layout: Layout, key: str) -> None:
    layout.session_file(key).unlink(missing_ok=True)


def read_session(layout: Layout, key: str) -> SessionSpec:
    raw = _read_bounded(
        layout.session_file(key), MAX_SESSION_FILE_BYTES, "session file", follow_symlinks=False
    )
    spec = SessionSpec.from_json(raw)
    if spec.key != key:
        raise SessionFormatError(
            f"the file name says {key!r} but the session's key is {spec.key!r}"
        )
    return spec


def _keys_in(directory: Path) -> list[str]:
    """The keys of the regular files named `<key>.json` in `directory`, nothing else."""
    try:
        entries = list(os.scandir(directory))
    except FileNotFoundError:
        return []
    keys = [
        entry.name.removesuffix(".json")
        for entry in entries
        if entry.name.endswith(".json")
        and KEY.fullmatch(entry.name.removesuffix(".json"))
        and entry.is_file(follow_symlinks=False)
    ]
    return sorted(keys)


def session_keys(layout: Layout) -> list[str]:
    return _keys_in(layout.sessions_dir)


def status_keys(layout: Layout) -> list[str]:
    return _keys_in(layout.status_dir)


def write_status(layout: Layout, key: str, status: SessionStatus) -> None:
    layout.status_dir.mkdir(parents=True, exist_ok=True)
    atomic_write(layout.status_file(key), status.to_json())


def read_status(layout: Layout, key: str) -> SessionStatus | None:
    try:
        raw = _read_bounded(
            layout.status_file(key), MAX_STATUS_FILE_BYTES, "status file", follow_symlinks=True
        )
    except FileNotFoundError:
        return None
    return SessionStatus.from_json(raw)


def wait_for_status(  # noqa: PLR0913 - the clock and the sleep are injected so tests never wait
    root: Path | str | Layout,
    key: str,
    states: Collection[str],
    timeout: float,
    *,
    poll_interval: float = DEFAULT_POLL_INTERVAL_S,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> SessionStatus:
    """Blocks until the daemon's status of `key` is in `states`; raises `TimeoutError` if not."""
    layout = root if isinstance(root, Layout) else Layout(Path(root))
    checked_key(key)
    deadline = clock() + timeout
    while True:
        try:
            status = read_status(layout, key)
        except (SessionFormatError, OSError):
            status = None
        if status is not None and status.state in states:
            return status
        remaining = deadline - clock()
        if remaining <= 0:
            raise TimeoutError(f"session {key} did not reach {sorted(states)} within {timeout}s")
        sleep(min(poll_interval, remaining))
