"""The control service's half of the fake local network: sessions, presets and health.

`guest-control` answers the backend, which opens a session before it submits a sample and closes it
when the analysis ends. A session is three things that must agree, and this module is the only
place that keeps them so:

- the firewall's ledger (`guest-firewall lan-open`/`lan-close`, run as a subprocess because the
  firewall's rules are consistent only under the lock that command takes, and this service is
  another process),
- the session file the `lan-sim` daemon reads (`guest_engine/lan_session.py` is the contract),
- the daemon's log of what the guest did, copied into the analysis folder when the session closes.

Opening fails closed: any error, a `failed` status or a daemon that does not answer in time
retracts the file and closes the firewall, so nothing stays open for an analysis that was refused.
Closing attempts every step whatever the one before did, because a daemon that is stuck must not
keep the firewall open. A restart of the control service closes nothing: the backend reconciles
(`GET /lan/sessions` lists every key either half still holds). A restart of the container drops both
halves together: `guest-firewall init` clears the ledger and /run is a tmpfs.

Preset accounts go into the session file, which the daemon needs, and nowhere else: not into the
firewall's input, a log line or an answer.
"""

import json
import re
import tempfile
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from analysis_files import Placement, place_once

from guest_engine.errors import Conflict, GuestNotFound, InvalidParameters
from guest_engine.lan_firewall import LanSession, LanTarget
from guest_engine.lan_presets import Preset, load_presets
from guest_engine.lan_session import (
    KEY,
    PRESET_ID,
    HostSpec,
    Layout,
    ServiceSpec,
    SessionFormatError,
    SessionSpec,
    publish_session,
    read_session,
    read_status,
    retract_session,
    session_keys,
    wait_for_status,
)
from guest_engine.media import MediaProblem, Runner, run_command
from guest_engine.profile import SLUG

DAEMON_TIMEOUT_S = 20.0
STATUS_POLL_S = 0.25
FIREWALL_TIMEOUT_S = 60
# The daemon touches its heartbeat every poll (0.5 s); this is ten polls, so a busy pass is not
# mistaken for a dead daemon.
HEARTBEAT_STALE_AFTER_S = 5.0
# The daemon caps its log at 8 MB plus the closing records; twice that is a log gone wrong.
EVENTS_FILE = Placement(folder="lansim", name="events.jsonl", limit=16 * 1024 * 1024)
FIREWALL_MESSAGE_LIMIT = 300

type Answer = tuple[int, dict[str, Any]]


class FirewallError(RuntimeError):
    """`guest-firewall` refused or could not run; the message is its own, without any account."""


class FirewallCommand:
    """The `guest-firewall lan-*` commands, run through the injected runner."""

    def __init__(self, command: Sequence[str], runner: Runner = run_command) -> None:
        self._command = list(command)
        self._runner = runner

    def open_session(self, session: Mapping[str, Any]) -> None:
        self._run(["lan-open"], stdin=json.dumps(session))

    def close_session(self, key: str) -> None:
        self._run(["lan-close", key])

    def keys(self) -> list[str]:
        listed = self._run(["lan-list"]).splitlines()
        return [line for line in listed if KEY.fullmatch(line)]

    def _run(self, arguments: list[str], stdin: str | None = None) -> str:
        command = [*self._command, *arguments]
        try:
            if stdin is None:
                result = self._runner(command, FIREWALL_TIMEOUT_S)
            else:
                # The runner hands the program a file, not a string.
                with tempfile.TemporaryFile() as file:
                    file.write(stdin.encode())
                    file.seek(0)
                    result = self._runner(command, FIREWALL_TIMEOUT_S, file)
        except MediaProblem as problem:
            raise FirewallError(f"{problem.detail} did not run ({problem.fault})") from problem
        if result.returncode != 0:
            said = result.stderr.strip() or f"exit status {result.returncode}"
            raise FirewallError(said[:FIREWALL_MESSAGE_LIMIT])
        return result.stdout


@dataclass(frozen=True)
class LanSettings:
    layout: Layout
    presets_dir: Path
    subnet: str
    storage: Path
    firewall_command: Sequence[str]


class LanSessions:
    def __init__(  # noqa: PLR0913 - the collaborators a test replaces
        self,
        settings: LanSettings,
        guest_address: Callable[[str], str],
        runner: Runner = run_command,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        wall_clock: Callable[[], float] = time.time,
        log: Callable[[str], None] = lambda _message: None,
    ) -> None:
        self._settings = settings
        self._layout = settings.layout
        self._guest_address = guest_address
        self._firewall = FirewallCommand(settings.firewall_command, runner)
        self._clock = clock
        self._sleep = sleep
        self._wall_clock = wall_clock
        self._log = log
        # Held while a session is checked against the others and published, so two requests
        # cannot both find a guest's address free.
        self._publishing = threading.Lock()

    # --- presets and health -----------------------------------------------------------------

    def presets(self) -> Answer:
        try:
            presets = self._load_presets()
        except (ValueError, OSError) as unloadable:
            return 500, {"error": _unloadable_presets_message(unloadable)}
        return 200, {"presets": [preset.public() for preset in presets]}

    def health(self) -> Answer:
        reason = self._daemon_problem() or self._presets_problem()
        return 200, {"ready": reason is None, "reason": reason}

    def _daemon_problem(self) -> str | None:
        try:
            heartbeat = self._layout.alive_file.stat().st_mtime
        except OSError:
            return "the fake-host daemon is not running (it has written no heartbeat)"
        silent_for = self._wall_clock() - heartbeat
        if silent_for > HEARTBEAT_STALE_AFTER_S:
            return f"the fake-host daemon has not answered for {silent_for:.0f} s"
        return None

    def _presets_problem(self) -> str | None:
        try:
            self._load_presets()
        except (ValueError, OSError) as unloadable:
            return _unloadable_presets_message(unloadable)
        return None

    def _load_presets(self) -> list[Preset]:
        return load_presets(self._settings.presets_dir, self._settings.subnet)

    # --- listing ----------------------------------------------------------------------------

    def keys(self) -> Answer:
        """Every key either half of a session still holds, so a half left by a restart is seen
        and closed by whoever reconciles."""
        try:
            in_firewall = self._firewall.keys()
        except FirewallError as unreadable:
            return 500, {"error": f"the firewall's sessions cannot be listed: {unreadable}"}
        return 200, {"keys": sorted({*session_keys(self._layout), *in_firewall})}

    # --- opening ----------------------------------------------------------------------------

    def open(self, body: Mapping[str, Any]) -> Answer:
        """Raises `InvalidParameters`, `GuestNotFound` and `Conflict` for a request to refuse;
        every other failure is a 503 with the reason, after closing whatever was started."""
        key, guest, preset_id = _open_request(body)
        address = self._guest_address(guest)
        try:
            preset = self._preset(preset_id)
            spec = _session_spec(key, address, preset)
            session = _lan_session(key, address, preset)
        except (ValueError, OSError) as unusable:
            return 503, {"error": _unloadable_presets_message(unusable)}
        redact = _redactor(spec)
        with self._publishing:
            already_open = self._reject_conflict(key, address, preset.id)
            try:
                self._firewall.open_session(asdict(session))
                if not already_open:
                    publish_session(self._layout, spec)
            except Exception as error:  # noqa: BLE001 - fail closed on anything
                return self._abandon(key, _explain(error), redact)
        return self._answer_when_listening(key, guest, preset.id, redact)

    def _preset(self, preset_id: str) -> Preset:
        found = next((p for p in self._load_presets() if p.id == preset_id), None)
        if found is None:
            raise GuestNotFound(f"no LAN preset named {preset_id}")
        return found

    def _reject_conflict(self, key: str, address: str, preset_id: str) -> bool:
        """True when this very session is already published (opening it again is idempotent)."""
        existing = self._read_session(key)
        if existing is not None:
            if (existing.guest_address, existing.preset_id) != (address, preset_id):
                raise Conflict(f"session {key} is already open for another guest or preset")
            return True
        for other in session_keys(self._layout):
            holder = self._read_session(other)
            if other != key and holder is not None and holder.guest_address == address:
                raise Conflict(f"the guest's address {address} is already held by session {other}")
        return False

    def _read_session(self, key: str) -> SessionSpec | None:
        try:
            return read_session(self._layout, key)
        except (SessionFormatError, OSError):
            return None

    def _answer_when_listening(
        self, key: str, guest: str, preset_id: str, redact: Callable[[str], str]
    ) -> Answer:
        try:
            status = wait_for_status(
                self._layout,
                key,
                {"listening", "failed"},
                DAEMON_TIMEOUT_S,
                poll_interval=STATUS_POLL_S,
                clock=self._clock,
                sleep=self._sleep,
            )
        except TimeoutError:
            why = f"the fake hosts did not start within {DAEMON_TIMEOUT_S:.0f} s"
            return self._abandon(key, why, redact)
        except Exception as error:  # noqa: BLE001 - fail closed on anything
            return self._abandon(key, _explain(error), redact)
        if status.state == "failed":
            return self._abandon(key, status.error or "the daemon failed the session", redact)
        self._log(f"lan: opened session {key} for {guest} ({preset_id})")
        return 201, {"key": key}

    def _abandon(self, key: str, why: str, redact: Callable[[str], str]) -> Answer:
        problems = self._tear_down(key)
        said = why if not problems else f"{why}; and the session could not be closed: {problems}"
        self._log(f"lan: opening session {key} failed, nothing left open: {redact(said)}")
        return 503, {"error": redact(said)}

    def _tear_down(self, key: str) -> str:
        problems = []
        try:
            retract_session(self._layout, key)
        except OSError as failed:
            problems.append(f"the session file could not be removed: {failed.strerror}")
        try:
            self._firewall.close_session(key)
        except FirewallError as unclosed:
            problems.append(str(unclosed))
        self._delete_leftovers(key, keep_log=False)
        return "; ".join(problems)

    # --- closing ----------------------------------------------------------------------------

    def close(self, key: str, task_id: int | None) -> Answer:
        """Retract, wait for the daemon, copy the log, close the firewall, clean up: each step is
        tried whatever happened before, and only the firewall's failure is an error."""
        warnings: list[str] = []
        if self._retract(key, warnings):
            self._await_closed(key, warnings)
        copied, keep_log = self._copy_events(key, task_id, warnings)
        unclosed = self._close_firewall(key)
        self._delete_leftovers(key, keep_log=keep_log)
        self._log(f"lan: closed session {key} (events copied: {'yes' if copied else 'no'})")
        if unclosed:
            return 500, {"error": f"the firewall could not close session {key}: {unclosed}"}
        return 200, {"copied": copied, **({"warnings": warnings} if warnings else {})}

    def _retract(self, key: str, warnings: list[str]) -> bool:
        """Whether the daemon has something to close now: a file that could not be removed leaves
        it nothing to notice, and a key it never heard of nothing to close."""
        with self._publishing:
            was_published = key in session_keys(self._layout)
            try:
                retract_session(self._layout, key)
            except OSError as failed:
                warnings.append(
                    f"the session file of {key} could not be removed: {failed.strerror}"
                )
                return False
        return was_published or self._status_state(key) not in (None, "closed")

    def _status_state(self, key: str) -> str | None:
        try:
            status = read_status(self._layout, key)
        except (SessionFormatError, OSError):
            return None
        return status.state if status else None

    def _await_closed(self, key: str, warnings: list[str]) -> None:
        try:
            wait_for_status(
                self._layout,
                key,
                {"closed"},
                DAEMON_TIMEOUT_S,
                poll_interval=STATUS_POLL_S,
                clock=self._clock,
                sleep=self._sleep,
            )
        except TimeoutError:
            warnings.append(
                f"the fake-host daemon did not confirm that {key} closed within"
                f" {DAEMON_TIMEOUT_S:.0f} s; its log may be incomplete"
            )

    def _copy_events(self, key: str, task_id: int | None, warnings: list[str]) -> tuple[bool, bool]:
        """(copied, keep the staged log): the log is kept only when the copy failed in a way a
        retry could mend."""
        if task_id is None:
            return False, False
        try:
            placed = place_once(
                self._layout.log_file(key), self._settings.storage, task_id, EVENTS_FILE
            )
        except FileNotFoundError:
            self._log(f"lan: session {key} has no log or task {task_id} has no analysis folder")
            return False, False
        except OSError as failed:
            warnings.append(
                f"the events of {key} could not be copied to task {task_id}:"
                f" {failed.strerror or type(failed).__name__}"
            )
            return False, True
        if not placed:
            self._log(f"lan: task {task_id} already has {EVENTS_FILE.name}; the first copy stays")
        return placed, False

    def _close_firewall(self, key: str) -> str | None:
        try:
            self._firewall.close_session(key)
        except FirewallError as unclosed:
            return str(unclosed)
        return None

    def _delete_leftovers(self, key: str, *, keep_log: bool) -> None:
        leftovers = [self._layout.status_file(key)]
        if not keep_log:
            leftovers.append(self._layout.log_file(key))
        for leftover in leftovers:
            try:
                leftover.unlink(missing_ok=True)
            except OSError as failed:
                self._log(f"lan: {leftover.name} could not be deleted: {failed.strerror}")


# --- pure helpers -----------------------------------------------------------------------------


def _open_request(body: Mapping[str, Any]) -> tuple[str, str, str]:
    problems = {}
    for field, pattern in (("key", KEY), ("guest", SLUG), ("preset", PRESET_ID)):
        value = body.get(field)
        if not isinstance(value, str) or not pattern.fullmatch(value):
            problems[field] = f"must match {pattern.pattern}"
    if problems:
        raise InvalidParameters(problems)
    return body["key"], body["guest"], body["preset"]


def _lan_session(key: str, address: str, preset: Preset) -> LanSession:
    targets = tuple(
        LanTarget(host.address, tuple(service.port for service in host.services))
        for host in preset.hosts
    )
    return LanSession(key, address, targets)


def _session_spec(key: str, address: str, preset: Preset) -> SessionSpec:
    hosts = tuple(
        HostSpec(
            fqdn=host.fqdn,
            address=host.address,
            os_banner=host.os_banner,
            accounts=tuple((account.user, account.password) for account in host.accounts),
            services=tuple(
                ServiceSpec(service.kind, service.port, dict(service.options))
                for service in host.services
            ),
        )
        for host in preset.hosts
    )
    return SessionSpec(key, address, preset.id, hosts)


def _redactor(spec: SessionSpec) -> Callable[[str], str]:
    """Hides every account password in a message that came from outside (the daemon's reason)."""
    secrets = sorted(
        {password for host in spec.hosts for _user, password in host.accounts if password},
        key=len,
        reverse=True,
    )

    def redact(message: str) -> str:
        for secret in secrets:
            message = re.sub(re.escape(secret), "***", message)
        return message

    return redact


def _explain(error: Exception) -> str:
    return str(error) if isinstance(error, FirewallError) else f"{type(error).__name__}: {error}"


def _unloadable_presets_message(error: Exception) -> str:
    return f"the LAN presets cannot be loaded: {error}"
