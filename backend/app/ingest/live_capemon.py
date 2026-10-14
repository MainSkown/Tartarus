from collections.abc import Iterable, Mapping
from datetime import timedelta
from typing import Any

from app.ingest.capemon import SOURCE, SOURCE_FILE, api_event, call_events, derived_event
from app.ingest.capemon_calls import Call, read_call, read_identity
from app.ingest.capemon_rules import (
    PROCESS_CREATING_APIS,
    DerivationRun,
    created_child_pid,
    derive,
)
from app.ingest.clock import calibrated_offset, parse_clock
from app.ingest.ecs import EventFactory, ProcessIdentity
from app.ingest.protocol import IngestContext
from app.live.bson_log import CallRecord, EnvironRecord, LogRecord, ProcessRecord

Event = dict[str, Any]


class LiveCapemon:
    """Turns the records of capemon's live logs into the events the final ingest would build.

    Feed it with `update(file_key, records)` as each process log grows, in the order the records
    arrive; one `file_key` per log file. It keeps what the derivation rules remember between
    calls. Events are identical to `CapemonNormalizer`'s for the same calls (same ids, same
    fields) except `tartarus.phase` (`live`), `tartarus.raw` (the call as the parser read it, with
    no pretty values) and the registry value `type`, which only the report spells out.

    `event.sequence` is a counter of this instance: unique and rising in the order events are
    returned. A collector that merges several sources renumbers it.

    A child's `process-created` event is held back until the child's own log has opened, because
    the child's start time is part of its `process.entity_id`; `flush()` releases the ones whose
    child never logged. The clock offset comes from the first process record and stays.
    """

    source = SOURCE

    def __init__(self, context: IngestContext) -> None:
        self._context = context
        self._factory = EventFactory(
            context, source=SOURCE, source_file=SOURCE_FILE, module=SOURCE, phase="live"
        )
        self._offset: timedelta | None = None
        self._pid_of_file: dict[str, int] = {}
        self._entries: dict[int, dict[str, Any]] = {}
        self._names: dict[int | None, str | None] = {}
        self._run = DerivationRun()
        self._awaiting_child: dict[int, list[Call]] = {}

    @property
    def clock_offset(self) -> timedelta | None:
        """What is added to the guest clock; `None` until a process record has been seen."""
        return self._offset

    def update(self, file_key: str, records: Iterable[LogRecord]) -> list[Event]:
        calls: list[CallRecord] = []
        for record in records:
            if isinstance(record, CallRecord):
                calls.append(record)
            else:
                self._learn(file_key, record)
        events = self._release_known_children()
        for record in calls:
            events += self._events_for(file_key, record)
        return events

    def flush(self) -> list[Event]:
        """Releases the creations still waiting for a child log that has not opened."""
        return self._release(list(self._awaiting_child))

    def _learn(self, file_key: str, record: LogRecord) -> None:
        if isinstance(record, ProcessRecord):
            self._learn_process(file_key, record)
        elif isinstance(record, EnvironRecord) and (pid := self._pid_of_file.get(file_key)):
            self._entries[pid]["environ"] = record.values
            self._remember_identity(pid)

    def _learn_process(self, file_key: str, record: ProcessRecord) -> None:
        if self._offset is None:
            first_process = parse_clock(record.first_seen_text)
            if first_process is not None:
                self._offset = calibrated_offset(
                    self._context.started_at,
                    first_process,
                    self._context.host_registrations.get(record.pid),
                )
        self._pid_of_file[file_key] = record.pid
        self._names[record.pid] = record.name
        self._entries[record.pid] = {
            "process_id": record.pid,
            "parent_id": record.parent_pid,
            "process_name": record.name,
            "module_path": record.module_path,
            "first_seen": record.first_seen_text,
        }
        self._remember_identity(record.pid)

    def _remember_identity(self, pid: int) -> None:
        self._run.remember(self._identity(pid))

    def _identity(self, pid: int) -> ProcessIdentity:
        return read_identity(self._entries[pid], self._names, self._offset or timedelta(0))

    def _events_for(self, file_key: str, record: CallRecord) -> list[Event]:
        pid = self._pid_of_file.get(file_key)
        if pid is None:
            return []
        call = read_call(
            _call_document(record),
            record.index,
            self._identity(pid),
            self._offset or timedelta(0),
            self._context.started_at,
        )
        if call is None:
            return []
        if (child_pid := self._unseen_child(call)) is not None:
            self._awaiting_child.setdefault(child_pid, []).append(call)
            return [api_event(self._factory, call, self._context.analysis_id)]
        return list(call_events(self._factory, call, self._run, self._context.analysis_id))

    def _unseen_child(self, call: Call) -> int | None:
        child_pid = created_child_pid(call) if call.api in PROCESS_CREATING_APIS else None
        known = child_pid in self._run.created_children or (
            child_pid is not None and self._run.knows(child_pid)
        )
        return None if known else child_pid

    def _release_known_children(self) -> list[Event]:
        return self._release([pid for pid in self._awaiting_child if self._run.knows(pid)])

    def _release(self, child_pids: list[int]) -> list[Event]:
        events: list[Event] = []
        for child_pid in child_pids:
            for call in self._awaiting_child.pop(child_pid):
                derived = derive(call, self._run)
                if derived is not None:
                    events.append(
                        derived_event(self._factory, call, derived, self._context.analysis_id)
                    )
        return events


def _call_document(record: CallRecord) -> Mapping[str, Any]:
    """The call in the shape of a report's, so the report's reader builds the `Call` from it."""
    return {
        "id": record.index,
        "api": record.api,
        "category": record.category,
        "thread_id": record.thread_id,
        "timestamp": record.timestamp_text,
        "caller": record.caller,
        "parentcaller": record.parent_caller,
        "status": record.status,
        "return": record.return_value,
        "repeated": record.repeated,
        "arguments": [{"name": arg.name, "value": arg.value} for arg in record.arguments],
    }
