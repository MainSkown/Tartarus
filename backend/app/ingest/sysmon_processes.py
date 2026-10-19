"""The processes behind Sysmon events: who an event is about, and which of them are the sample's."""

from collections import defaultdict
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from app.ingest.capemon_rules import DerivationRun
from app.ingest.clock import parse_clock
from app.ingest.ecs import ProcessIdentity, base_name, process_fields
from app.ingest.reading import to_int
from app.ingest.windows_events import WindowsEvent

PROCESS_CREATED = 1
REMOTE_THREAD = 8
PROCESS_ACCESS = 10
# Events whose own `ProcessGuid`/`ProcessId`/`Image` name the process that acted.
ACTING_PROCESS_EVENTS = frozenset({1, 3, 5, 7, 11, 12, 13, 14, 22, 23, 26})
UNKNOWN_IMAGE = "<unknown process>"
NULL_GUID = "{00000000-0000-0000-0000-000000000000}"


class EventFields:
    """`EventData` by name, case-insensitively, with Sysmon's `-` for "nothing" read as absent.

    Sysmon spells the same field differently between events (`SourceProcessGuid` in EID 8,
    `SourceProcessGUID` in EID 10).
    """

    def __init__(self, data: Mapping[str, str]) -> None:
        self.data = data
        self._by_name = {name.casefold(): value for name, value in data.items()}

    def get(self, name: str) -> str | None:
        value = self._by_name.get(name.casefold())
        return None if value in (None, "", "-") else value

    def integer(self, name: str) -> int | None:
        return to_int(self.get(name))


@dataclass(frozen=True)
class Subject:
    """A process as an event names it; each part may be missing."""

    guid: str | None
    pid: int | None
    image: str | None

    @property
    def identifiable(self) -> bool:
        return self.guid is not None or self.pid is not None


def subject_of(fields: EventFields, prefix: str = "") -> Subject:
    """The process named by `<prefix>ProcessGuid`, `<prefix>ProcessId` and `<prefix>Image`."""
    guid = fields.get(f"{prefix}ProcessGuid")
    image = fields.get(f"{prefix}Image")
    return Subject(
        guid=None if guid == NULL_GUID else guid,
        pid=fields.integer(f"{prefix}ProcessId"),
        image=None if image == UNKNOWN_IMAGE else image,
    )


def acting_and_target(event_id: int, fields: EventFields) -> tuple[Subject | None, Subject | None]:
    """The process that did it and, for EID 8 and 10, the one it was done to."""
    if event_id in (REMOTE_THREAD, PROCESS_ACCESS):
        return subject_of(fields, "Source"), subject_of(fields, "Target")
    if event_id in ACTING_PROCESS_EVENTS:
        return subject_of(fields), None
    return None, None


def guest_time(event: WindowsEvent, fields: EventFields) -> datetime | None:
    """`UtcTime` (when it happened) on the guest's clock, else the log's write time."""
    return parse_clock(fields.get("UtcTime")) or event.system_time


@dataclass(frozen=True)
class StartedProcess:
    """What a process-create event (EID 1) says; the start is on the UTC clock."""

    guid: str
    pid: int
    image: str | None
    command_line: str | None
    start: datetime | None
    parent_guid: str | None
    parent_pid: int | None
    parent_image: str | None


class ProcessLedger:
    """Every process whose creation the log holds, by guid, with the tree they form.

    The log is read once to build this, before any event is judged, because the export is not in
    time order and a child's creation can precede its parent's in the file.
    """

    def __init__(self, started: Iterable[StartedProcess]) -> None:
        self._by_guid: dict[str, StartedProcess] = {}
        self._children: defaultdict[str, list[str]] = defaultdict(list)
        for process in started:
            self._by_guid[process.guid] = process
            if process.parent_guid is not None:
                self._children[process.parent_guid].append(process.guid)

    @classmethod
    def read(cls, events: Iterable[WindowsEvent], clock_offset: timedelta) -> "ProcessLedger":
        return cls(_started_processes(events, clock_offset))

    def get(self, guid: str | None) -> StartedProcess | None:
        return self._by_guid.get(guid) if guid is not None else None

    def __iter__(self) -> Iterator[StartedProcess]:
        return iter(self._by_guid.values())

    def descendants(self, roots: Iterable[str]) -> set[str]:
        """The roots and every process started, directly or not, by one of them."""
        found: set[str] = set()
        pending = list(roots)
        while pending:
            guid = pending.pop()
            if guid not in found:
                found.add(guid)
                pending.extend(self._children.get(guid, ()))
        return found


def _started_processes(
    events: Iterable[WindowsEvent], clock_offset: timedelta
) -> Iterator[StartedProcess]:
    for event in events:
        if event.event_id != PROCESS_CREATED:
            continue
        fields = EventFields(event.data)
        process = subject_of(fields)
        if process.guid is None or process.pid is None:
            continue
        parent = subject_of(fields, "Parent")
        moment = guest_time(event, fields)
        yield StartedProcess(
            guid=process.guid,
            pid=process.pid,
            image=process.image,
            command_line=fields.get("CommandLine"),
            start=None if moment is None else moment + clock_offset,
            parent_guid=parent.guid,
            parent_pid=parent.pid,
            parent_image=parent.image,
        )


class SampleProcesses:
    """The processes capemon monitored, which is what the report calls the sample's tree."""

    def __init__(self, identities: Iterable[ProcessIdentity]) -> None:
        known = list(identities)
        self._by_pid: defaultdict[int, list[ProcessIdentity]] = defaultdict(list)
        for identity in known:
            self._by_pid[identity.pid].append(identity)
        self._run = DerivationRun.of(known)

    def __bool__(self) -> bool:
        return bool(self._by_pid)

    def has_pid(self, pid: int | None) -> bool:
        return pid in self._by_pid

    def holds(self, pid: int | None, image: str | None) -> bool:
        return any(_same_image(identity, image) for identity in self._by_pid.get(pid or 0, ()))

    def identity_at(self, pid: int, image: str | None, when: datetime) -> ProcessIdentity | None:
        """The monitored process that held `pid` at `when`, if it is the one running `image`."""
        identity = self._run.process_at(pid, when)
        return identity if identity is not None and _same_image(identity, image) else None


def _same_image(identity: ProcessIdentity, image: str | None) -> bool:
    known = identity.name or (base_name(identity.executable) if identity.executable else None)
    return image is None or known is None or base_name(image).casefold() == known.casefold()


class SampleTree:
    """Which processes belong to the sample.

    The sample's processes are the ones capemon monitored, matched to the log by pid and image
    name, and everything they started (`ParentProcessGuid`). A process the log never saw start
    cannot be told apart from the sample by guid, so there the pid alone decides: a pid reused by
    an unrelated process is then kept, which is cheaper than losing the sample's events.
    """

    def __init__(self, sample: SampleProcesses, ledger: ProcessLedger) -> None:
        self._sample = sample
        self._ledger = ledger
        self._guids = ledger.descendants(self._roots())

    @property
    def has_sample(self) -> bool:
        return bool(self._sample)

    def contains(self, subject: Subject | None) -> bool:
        if subject is None:
            return False
        if subject.guid in self._guids:
            return True
        if self._ledger.get(subject.guid) is not None:
            return False
        return self._sample.has_pid(subject.pid)

    def _roots(self) -> Iterator[str]:
        for started in self._ledger:
            parent_unseen = self._ledger.get(started.parent_guid) is None
            if self._sample.holds(started.pid, started.image) or (
                parent_unseen and self._sample.has_pid(started.parent_pid)
            ):
                yield started.guid


class ProcessResolver:
    """The `process` section of an event: identity and entity id shared with capemon's."""

    def __init__(self, sample: SampleProcesses, ledger: ProcessLedger, analysis_id: int) -> None:
        self._sample = sample
        self._ledger = ledger
        self._analysis_id = analysis_id

    def section(self, event_id: int, fields: EventFields, when: datetime) -> dict[str, Any] | None:
        actor, _ = acting_and_target(event_id, fields)
        if actor is None or actor.pid is None:
            return None
        created = fields if event_id == PROCESS_CREATED else None
        thread = fields.integer("SourceThreadId") if event_id == PROCESS_ACCESS else None
        section = process_fields(
            self._identity(actor.pid, actor, created, when), self._analysis_id, thread_id=thread
        )
        if created is not None and (level := fields.get("IntegrityLevel")):
            section["integrity_level"] = level
        return section

    def _identity(
        self, pid: int, actor: Subject, created: EventFields | None, when: datetime
    ) -> ProcessIdentity:
        started = self._ledger.get(actor.guid)
        image = actor.image or (started.image if started else None)
        # capemon's `first_seen` is the start in the entity id; a monitored process takes it so
        # that its Sysmon and capemon events share one entity.
        shared = self._sample.identity_at(pid, image, when)
        start = shared.start if shared else (started.start if started else None)
        if created is not None:
            command_line, parent = created.get("CommandLine"), _parent_of(created)
        else:
            command_line, parent = (started.command_line if started else None), {}
        return ProcessIdentity(
            pid=pid,
            name=base_name(image) if image else None,
            executable=image,
            command_line=command_line,
            start=start,
            **parent,
        )


def _parent_of(created: EventFields) -> dict[str, Any]:
    parent = subject_of(created, "Parent")
    return {
        "parent_pid": parent.pid,
        "parent_name": base_name(parent.image) if parent.image else None,
        "parent_executable": parent.image,
        "parent_command_line": created.get("ParentCommandLine"),
    }
