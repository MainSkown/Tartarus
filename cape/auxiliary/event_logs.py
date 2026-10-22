"""Exports Windows event logs from the guest at the end of a run, through the CAPE agent.

A host-side auxiliary: it keeps working when the guest analyzer dies before it starts its own
modules (Defender kills it on the first read of a detected sample). Each channel is exported as
`<Events>` XML into the analysis folder, only the records written since `start()`.
"""

import base64
import binascii
import codecs
import importlib
import json
import logging
import re
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from http import HTTPStatus
from pathlib import Path
from typing import Any, Literal, Protocol
from xml.parsers import expat

from lib.cuckoo.common.abstracts import Auxiliary
from lib.cuckoo.common.constants import CUCKOO_ROOT

log = logging.getLogger(__name__)

AGENT_PORT = 8000
CONNECT_TIMEOUT_S = 5
# What the guest may hand back, as an HTTP body and as a document written to the analysis folder.
# The "agent" answering is whatever the sample left listening on the guest's port 8000.
MAX_EXPORT_BYTES = 256 * 1024 * 1024
ANSWER_CHUNK_BYTES = 64 * 1024
ANSWER_PREVIEW_CHARS = 80
BASELINE_TIMEOUT_S = 15
START_BUDGET_S = 90
# A guest can be slow to answer after its snapshot revert (11 s instead of 4 to 6, spike P3 task
# 397); the wait stops short of the start budget so the baselines still fit in it.
AGENT_WAIT_S = 60
AGENT_POLL_S = 2
# The slowest export (Sysmon, 120 s) plus the Defender settle wait (30 s) and the polls around it.
STOP_BUDGET_S = 180
# Defender quarantines a detected file about ten seconds after it detects it (1117 after 1116);
# the worst seen was 17.5 s.
SETTLE_CAP_S = 30
SETTLE_POLL_S = 3

# The agent splits commands POSIX-style: paths take forward slashes and a literal
# backslash is doubled.
WEVTUTIL = "C:/Windows/System32/wevtutil.exe"
REG = "C:/Windows/System32/reg.exe"
POWERSHELL = "C:/Windows/System32/WindowsPowerShell/v1.0/powershell.exe"
SYSMON_EXE = "C:/Windows/Sysmon64.exe"
ANSI_CODE_PAGE_KEY = r"HKLM\\SYSTEM\\CurrentControlSet\\Control\\Nls\\CodePage"

MISSING_EXPORTS_FILE = "aux/event_logs.json"
EMPTY_EVENTS = b"<Events>\n</Events>\n"
XML_FORBIDDEN_CONTROL_CHARACTERS = re.compile(rb"[\x00-\x08\x0b\x0c\x0e-\x1f]")
EVENT = re.compile(rb"<Event[ >].*?</Event>", re.DOTALL)
EVENT_ID = re.compile(rb"<EventID[^>]*>(\d+)<")
DETECTION_ID = re.compile(rb"<Data Name=['\"]Detection ID['\"]>([^<]*)<")
RECORD_COUNT = re.compile(rb"numberOfLogRecords:\s*(\d+)")
NEWEST_RECORD_ID = re.compile(rb"<EventRecordID>(\d+)<")
ACP = re.compile(rb"ACP\s+REG_SZ\s+(\d+)")
DETECTED, CLOSING = 1116, (1117, 1118, 1119)

POWERSHELL_EXPORT = """\
[Console]::OutputEncoding=[Text.Encoding]::UTF8
$ErrorActionPreference = 'SilentlyContinue'
$filter = '*[System[EventRecordID > {after}]]'
$records = Get-WinEvent -LogName '{channel}' -FilterXPath $filter -Oldest
'<Events>'
foreach ($record in $records) {{ $record.ToXml() }}
'</Events>'
"""


class Clock(Protocol):
    def now(self) -> float: ...
    def sleep(self, seconds: float) -> None: ...


class Agent(Protocol):
    def status(self, read_timeout: float) -> None: ...
    def execute(self, command: str, read_timeout: float) -> bytes: ...
    def store(self, guest_path: str, data: bytes, read_timeout: float) -> None: ...
    def remove(self, guest_path: str, read_timeout: float) -> None: ...


class BudgetExhaustedError(Exception):
    pass


class AgentAnswerError(Exception):
    pass


class DeadlineExceededError(Exception):
    pass


class SystemClock:
    def now(self) -> float:
        return time.monotonic()

    def sleep(self, seconds: float) -> None:
        time.sleep(seconds)


class GuestAgent:
    def __init__(self, ip: str, http: Any = None):
        self._base = f"http://{ip}:{AGENT_PORT}"
        self._http = http

    def status(self, read_timeout: float) -> None:
        self._send("get", "status", read_timeout)

    def execute(self, command: str, read_timeout: float) -> bytes:
        body = self._send(
            "post", "execute", read_timeout, data={"command": command, "encoding": "base64"}
        )
        stdout = json.loads(body)["stdout"]
        try:
            return base64.b64decode(stdout, validate=True)
        except binascii.Error:
            # The agent answered with its own text (an error, say), not the export: report it.
            raise AgentAnswerError(
                f"the guest agent's answer was not an export: {stdout[:ANSWER_PREVIEW_CHARS]!r}"
            ) from None

    def store(self, guest_path: str, data: bytes, read_timeout: float) -> None:
        self._send(
            "post",
            "store",
            read_timeout,
            data={"filepath": guest_path},
            files={"file": ("upload", data)},
        )

    def remove(self, guest_path: str, read_timeout: float) -> None:
        self._send("post", "remove", read_timeout, data={"path": guest_path})

    def _send(
        self, method: Literal["get", "post"], route: str, read_timeout: float, **form: Any
    ) -> bytes:
        # Imported here because the unit tests run on the stdlib alone; CAPE's python has requests.
        http = self._http or importlib.import_module("requests")

        def fetch(cancelled: threading.Event) -> bytes:
            # No redirects: requests would replay the POST to wherever the guest points it, and
            # the host can reach the backend and OpenSearch.
            answer = getattr(http, method)(
                f"{self._base}/{route}",
                timeout=(CONNECT_TIMEOUT_S, read_timeout),
                allow_redirects=False,
                stream=True,
                **form,
            )
            try:
                return read_answer(answer, cancelled)
            finally:
                answer.close()

        return run_within(CONNECT_TIMEOUT_S + read_timeout, fetch)


def read_answer(answer: Any, cancelled: threading.Event) -> bytes:
    if HTTPStatus.MULTIPLE_CHOICES <= answer.status_code < HTTPStatus.BAD_REQUEST:
        raise AgentAnswerError(
            f"the guest agent answered {answer.status_code}, a redirect; refused"
        )
    answer.raise_for_status()
    body = bytearray()
    for chunk in answer.iter_content(ANSWER_CHUNK_BYTES):
        if cancelled.is_set():
            raise DeadlineExceededError("the call was abandoned at its deadline")
        body += chunk
        if len(body) > MAX_EXPORT_BYTES:
            raise AgentAnswerError(
                f"the guest agent's answer is larger than {MAX_EXPORT_BYTES} bytes"
            )
    return bytes(body)


def run_within(seconds: float, work: Callable[[threading.Event], bytes]) -> bytes:
    """Runs `work` and gives up on it after `seconds` in total.

    requests' read timeout restarts with every byte received, so a guest that drips one byte every
    few seconds never trips it and would hold the machine slot for good. The worker is a daemon
    thread: when abandoned it stops at its next chunk (it holds at most MAX_EXPORT_BYTES) or when
    the read timeout closes the connection.
    """
    cancelled = threading.Event()
    outcome: dict[str, Any] = {}

    def target() -> None:
        try:
            outcome["value"] = work(cancelled)
        except BaseException as error:  # noqa: BLE001 - handed to the caller's thread below
            outcome["error"] = error

    worker = threading.Thread(target=target, daemon=True)
    worker.start()
    worker.join(seconds)
    if worker.is_alive():
        cancelled.set()
        raise DeadlineExceededError(
            f"the guest agent did not finish answering within {seconds:g} s"
        )
    if "error" in outcome:
        raise outcome["error"]
    return bytes(outcome["value"])


class Budget:
    def __init__(self, clock: Clock, seconds: float):
        self._clock = clock
        self._deadline = clock.now() + seconds

    def remaining(self) -> float:
        return self._deadline - self._clock.now()

    def bound(self, timeout: float) -> float:
        left = self.remaining()
        if left <= 0:
            raise BudgetExhaustedError("the time budget is used up")
        return min(timeout, left)


@contextmanager
def logged_failure(description: str) -> Iterator[None]:
    try:
        yield
    except Exception as error:  # noqa: BLE001 - CAPE aborts the task on an exception out of start() or stop()
        log.warning("%s failed: %s", description, error)


@dataclass(frozen=True)
class GuestConfig:
    """A file pushed to the guest and applied before the baseline is read."""

    source: Path
    guest_path: str
    apply_command: str


@dataclass(frozen=True)
class Channel:
    """One event log: where its export lands and how the guest hands it over.

    `ansi` exports with wevtutil, two orders of magnitude faster than PowerShell but written in the
    guest's ANSI code page; `utf-8` exports through PowerShell's `ToXml()`, lossless but 8 ms
    an event.
    `is_settled` says when late records the run provoked have arrived.
    """

    name: str
    target: str
    guest_encoding: Literal["ansi", "utf-8"]
    is_settled: Callable[[bytes], bool] | None = None
    config: GuestConfig | None = None
    read_timeout_s: float = 30


def every_detection_closed(document: bytes) -> bool:
    detected: set[bytes] = set()
    closed: set[bytes] = set()
    for event in EVENT.findall(document):
        event_id, detection = EVENT_ID.search(event), DETECTION_ID.search(event)
        if not (event_id and detection):
            continue
        if int(event_id.group(1)) == DETECTED:
            detected.add(detection.group(1))
        elif int(event_id.group(1)) in CLOSING:
            closed.add(detection.group(1))
    return detected <= closed


def powershell_command(script: str) -> str:
    encoded = base64.b64encode(script.encode("utf-16-le")).decode()
    return f"{POWERSHELL} -NoProfile -EncodedCommand {encoded}"


def events_document(raw: bytes) -> bytes | None:
    """The export as a well-formed `<Events>` document, or None for anything else.

    Whatever precedes the wrapper (a BOM, a stray console line) is dropped; starting the parse at
    the wrapper also leaves no room for a DTD, which can only come before the root element.
    """
    if not raw.strip():
        return EMPTY_EVENTS
    start = raw.find(b"<Events")
    if start < 0:
        return None
    cleaned = XML_FORBIDDEN_CONTROL_CHARACTERS.sub(b"", raw[start:])
    return cleaned if is_well_formed(cleaned) else None


def is_well_formed(document: bytes) -> bool:
    try:
        expat.ParserCreate().Parse(document, True)
    except expat.ExpatError:
        return False
    return True


SYSMON = Channel(
    "Microsoft-Windows-Sysmon/Operational",
    "sysmon/sysmon.xml",
    "ansi",
    config=GuestConfig(
        source=Path("/usr/local/lib/tartarus/profiles/windows/sysmon-config.xml"),
        guest_path="C:/Windows/Temp/sysmon-update.xml",
        apply_command=f"{SYSMON_EXE} -accepteula -c {{path}}",
    ),
    read_timeout_s=120,
)
DEFENDER = Channel(
    "Microsoft-Windows-Windows Defender/Operational",
    "aux/defender.xml",
    "utf-8",
    is_settled=every_detection_closed,
)
CHANNELS = (SYSMON, DEFENDER)


class EventLogCollector:
    def __init__(self, agent: Agent, clock: Clock, channels: tuple[Channel, ...]):
        self._agent = agent
        self._clock = clock
        self._channels = channels
        self._baselines: dict[str, int | None] = {}
        self._codec: str | None = None
        self._missing: dict[str, str] = {}

    def start(self) -> None:
        budget = Budget(self._clock, START_BUDGET_S)
        if not self._wait_for_agent(budget):
            return
        if any(channel.guest_encoding == "ansi" for channel in self._channels):
            with logged_failure("reading the guest's ANSI code page"):
                self._codec = self._read_codec(budget)
        for channel in self._channels:
            baseline = None
            with self._recorded_failure(channel, "the baseline could not be read"):
                baseline = self._baseline(channel, budget)
            self._baselines[channel.name] = baseline

    def export_to(self, folder: Path) -> None:
        budget = Budget(self._clock, STOP_BUDGET_S)
        for channel in self._channels:
            baseline = self._baselines.get(channel.name)
            if baseline is None:
                continue
            with self._recorded_failure(channel, "the export failed"):
                self._write(folder, channel, self._export(channel, baseline, budget))
        if self._missing:
            with logged_failure("writing the list of missing exports"):
                self._write_missing_exports(folder)

    def _wait_for_agent(self, budget: Budget) -> bool:
        waiting = Budget(self._clock, AGENT_WAIT_S)
        while True:
            try:
                self._agent.status(budget.bound(CONNECT_TIMEOUT_S))
                return True
            except Exception as error:  # noqa: BLE001 - any failure to reach the agent means wait
                failure = error
            if waiting.remaining() <= AGENT_POLL_S:
                break
            self._clock.sleep(AGENT_POLL_S)
        log.warning("the guest agent did not answer within %d s: %s", AGENT_WAIT_S, failure)
        for channel in self._channels:
            self._missing[channel.name] = (
                f"the guest agent did not answer within {AGENT_WAIT_S} s ({failure})"
            )
        return False

    @contextmanager
    def _recorded_failure(self, channel: Channel, what: str) -> Iterator[None]:
        try:
            yield
        except Exception as error:  # noqa: BLE001 - CAPE aborts the task on an exception out of start() or stop()
            log.warning("%s: %s: %s", channel.name, what, error)
            self._missing[channel.name] = f"{what}: {error}"

    def _write_missing_exports(self, folder: Path) -> None:
        marker = folder / MISSING_EXPORTS_FILE
        marker.parent.mkdir(parents=True, exist_ok=True)
        entries = [{"channel": name, "reason": reason} for name, reason in self._missing.items()]
        marker.write_text(json.dumps({"missing": entries}, indent=2))

    def _read_codec(self, budget: Budget) -> str | None:
        answer = self._agent.execute(
            f"{REG} query {ANSI_CODE_PAGE_KEY} /v ACP", budget.bound(BASELINE_TIMEOUT_S)
        )
        found = ACP.search(answer)
        if not found:
            return None
        try:
            return codecs.lookup(f"cp{found.group(1).decode()}").name
        except LookupError:
            return None

    def _baseline(self, channel: Channel, budget: Budget) -> int | None:
        """The newest record id before the run, or None: no baseline means no export."""
        records = self._record_count(channel, budget)
        if records is None:
            log.info("%s is not on this guest; nothing to export", channel.name)
            return None
        if channel.guest_encoding == "ansi" and self._codec is None:
            self._miss(channel, "needs the guest's ANSI code page, which could not be read")
            return None
        if channel.config:
            self._apply_config(channel.config, budget)
        newest = self._newest_record_id(channel, budget)
        if newest is None and records > 0:
            self._miss(channel, "the newest record id could not be read")
            return None
        return newest or 0

    def _miss(self, channel: Channel, reason: str) -> None:
        log.warning("%s: %s", channel.name, reason)
        self._missing[channel.name] = reason

    def _record_count(self, channel: Channel, budget: Budget) -> int | None:
        answer = self._agent.execute(
            f'{WEVTUTIL} gli "{channel.name}"', budget.bound(BASELINE_TIMEOUT_S)
        )
        found = RECORD_COUNT.search(answer)
        return int(found.group(1)) if found else None

    def _newest_record_id(self, channel: Channel, budget: Budget) -> int | None:
        command = f'{WEVTUTIL} query-events "{channel.name}" /c:1 /rd:true /f:xml'
        found = NEWEST_RECORD_ID.search(
            self._agent.execute(command, budget.bound(BASELINE_TIMEOUT_S))
        )
        return int(found.group(1)) if found else None

    def _apply_config(self, config: GuestConfig, budget: Budget) -> None:
        try:
            data = config.source.read_bytes()
        except OSError as error:
            log.warning("cannot read %s: %s", config.source, error)
            return
        with logged_failure(f"applying {config.source.name}"):
            self._agent.store(config.guest_path, data, budget.bound(BASELINE_TIMEOUT_S))
            try:
                self._agent.execute(
                    config.apply_command.format(path=config.guest_path),
                    budget.bound(BASELINE_TIMEOUT_S),
                )
            finally:
                with logged_failure(f"removing {config.guest_path} from the guest"):
                    self._agent.remove(config.guest_path, budget.bound(BASELINE_TIMEOUT_S))

    def _export(self, channel: Channel, baseline: int, budget: Budget) -> bytes:
        if not channel.is_settled:
            return self._export_once(channel, baseline, budget)
        started = self._clock.now()
        while True:
            xml = self._export_once(channel, baseline, budget)
            if channel.is_settled(xml):
                return xml
            if self._clock.now() - started >= SETTLE_CAP_S or budget.remaining() <= SETTLE_POLL_S:
                log.warning(
                    "%s: detections still open after %.0f s",
                    channel.name,
                    self._clock.now() - started,
                )
                return xml
            self._clock.sleep(SETTLE_POLL_S)

    def _export_once(self, channel: Channel, baseline: int, budget: Budget) -> bytes:
        timeout = budget.bound(channel.read_timeout_s)
        if channel.guest_encoding == "utf-8":
            script = POWERSHELL_EXPORT.format(channel=channel.name, after=baseline)
            return self._agent.execute(powershell_command(script), timeout)
        query = f"*[System[EventRecordID > {baseline}]]"
        command = f'{WEVTUTIL} query-events "{channel.name}" /e:Events /format:xml /query:"{query}"'
        return (
            self._agent.execute(command, timeout).decode(self._codec or "ascii", "replace").encode()
        )

    def _write(self, folder: Path, channel: Channel, raw: bytes) -> None:
        document = events_document(raw)
        if document is None:
            self._miss(channel, "the guest did not return an Events document; nothing written")
            return
        if len(document) > MAX_EXPORT_BYTES:
            self._miss(
                channel, f"the export is larger than {MAX_EXPORT_BYTES} bytes; nothing written"
            )
            return
        target = folder / channel.target
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(document)
        log.info(
            "exported %s: %d events, %d bytes",
            channel.name,
            document.count(b"<Event "),
            len(document),
        )


class EventLogs(Auxiliary):
    collector: EventLogCollector | None = None

    def start(self) -> None:
        with logged_failure("starting the event log export"):
            self.collector = EventLogCollector(GuestAgent(self.machine.ip), SystemClock(), CHANNELS)
            self.collector.start()

    def stop(self) -> None:
        if self.collector is None:
            return
        analysis_folder = Path(CUCKOO_ROOT) / "storage" / "analyses" / str(self.task.id)
        with logged_failure("the event log export"):
            self.collector.export_to(analysis_folder)
