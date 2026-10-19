"""A fake Windows guest behind the CAPE agent, with event logs, and a clock the test moves."""

import base64
import re
from dataclasses import dataclass, field

EVENT_NAMESPACE = "http://schemas.microsoft.com/win/2004/08/events/event"
ACP_BY_CODEPAGE = {"1250": "cp1250", "1252": "cp1252"}


class FakeClock:
    def __init__(self):
        self.seconds = 1000.0

    def now(self) -> float:
        return self.seconds

    def sleep(self, seconds: float) -> None:
        self.seconds += seconds


def event_xml(record_id: int, event_id: int = 1, **data: str) -> str:
    named = "".join(
        f"<Data Name='{name.replace('_', ' ')}'>{value}</Data>" for name, value in data.items()
    )
    return (
        f"<Event xmlns='{EVENT_NAMESPACE}'><System><EventID>{event_id}</EventID>"
        f"<EventRecordID>{record_id}</EventRecordID></System><EventData>{named}</EventData></Event>"
    )


@dataclass
class Record:
    record_id: int
    xml: str
    visible_at: float


@dataclass
class FakeGuest:
    """Answers the commands the module sends to the agent as wevtutil, reg and PowerShell do."""

    clock: FakeClock
    code_page: str = "1250"
    call_cost: float = 0.5
    empty_wevtutil_prints_wrapper: bool = False
    logs: dict[str, list[Record]] = field(default_factory=dict)
    commands: list[str] = field(default_factory=list)
    timeouts: list[float] = field(default_factory=list)
    stored: dict[str, bytes] = field(default_factory=dict)
    removed: list[str] = field(default_factory=list)
    broken_commands: dict[str, Exception] = field(default_factory=dict)
    sysmon_applied_config: bytes | None = None
    store_failure: Exception | None = None

    def add_log(self, channel: str) -> None:
        self.logs.setdefault(channel, [])

    def add_event(self, channel: str, event_id: int = 1, delay: float = 0.0, **data: str) -> int:
        records = self.logs.setdefault(channel, [])
        record_id = records[-1].record_id + 1 if records else 1
        records.append(
            Record(record_id, event_xml(record_id, event_id, **data), self.clock.now() + delay)
        )
        return record_id

    def execute(self, command: str, timeout: float) -> bytes:
        self.clock.sleep(self.call_cost)
        self.commands.append(command)
        self.timeouts.append(timeout)
        for fragment, error in self.broken_commands.items():
            if fragment in command:
                raise error
        return self._answer(command)

    def store(self, guest_path: str, data: bytes, timeout: float) -> None:
        self.clock.sleep(self.call_cost)
        self.timeouts.append(timeout)
        if self.store_failure:
            raise self.store_failure
        self.stored[guest_path] = data

    def remove(self, guest_path: str, timeout: float) -> None:
        self.clock.sleep(self.call_cost)
        self.timeouts.append(timeout)
        self.removed.append(guest_path)

    def _visible(self, channel: str) -> list[Record]:
        return [
            record for record in self.logs.get(channel, []) if record.visible_at <= self.clock.now()
        ]

    def _answer(self, command: str) -> bytes:
        if "reg.exe" in command:
            return f"\r\n    ACP    REG_SZ    {self.code_page}\r\n".encode()
        if "-EncodedCommand" in command:
            return self._powershell(command)
        if "Sysmon64.exe" in command:
            return self._apply_sysmon_config(command)
        channel = re.search(r'wevtutil\.exe \S+ "([^"]+)"', command).group(1)
        if " gli " in command:
            return self._log_info(channel)
        if "/rd:true" in command:
            visible = self._visible(channel)
            return visible[-1].xml.encode(self._codec) if visible else b""
        return self._wevtutil_export(command, channel)

    @property
    def _codec(self) -> str:
        return ACP_BY_CODEPAGE[self.code_page]

    def _log_info(self, channel: str) -> bytes:
        if channel not in self.logs:
            return b""
        return f"creationTime: x\r\nnumberOfLogRecords: {len(self._visible(channel))}\r\n".encode()

    def _wevtutil_export(self, command: str, channel: str) -> bytes:
        after = int(re.search(r"EventRecordID > (\d+)", command).group(1))
        events = [record.xml for record in self._visible(channel) if record.record_id > after]
        if not events and not self.empty_wevtutil_prints_wrapper:
            return b""
        return ("<Events>\r\n" + "\r\n".join(events) + "\r\n</Events>\r\n").encode(
            self._codec, "replace"
        )

    def _powershell(self, command: str) -> bytes:
        script = base64.b64decode(command.rsplit(" ", 1)[1]).decode("utf-16-le")
        channel = re.search(r"-LogName '([^']+)'", script).group(1)
        after = int(re.search(r"EventRecordID > (\d+)", script).group(1))
        assert "OutputEncoding=[Text.Encoding]::UTF8" in script
        events = [record.xml for record in self._visible(channel) if record.record_id > after]
        return (
            "<Events>\r\n" + "".join(event + "\r\n" for event in events) + "</Events>\r\n"
        ).encode()

    def _apply_sysmon_config(self, command: str) -> bytes:
        path = command.rsplit(" ", 1)[1]
        self.sysmon_applied_config = self.stored[path]
        self.add_event("Microsoft-Windows-Sysmon/Operational", event_id=16)
        return b"Configuration updated.\r\n"
