"""Turns the Sysmon log a guest exports (`sysmon/sysmon.xml`) into process, file, registry and
network events.

The log is read twice and never held whole: a first pass collects the process creations (EID 1) to
learn the sample's process tree, a second judges each event (`app.ingest.sysmon_noise`) and keeps
the sample's. Only those are buffered, to emit them oldest first: the guest's exporter writes
oldest first, CAPE's own newest first, and the rest of the pipeline sorts by time anyway.

Times: `UtcTime` is the guest's clock, brought to true UTC with the offset capemon's times get.
Event ids follow the position of the record in the file, so they do not move when a noise rule
changes. Rules and mapping: docs/specs/data-model.md, "Sysmon".
"""

from collections import Counter
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from app.ingest.capemon_calls import read_processes
from app.ingest.clock import guest_clock_offset
from app.ingest.ecs import EventFactory, SourceRecord, truncate
from app.ingest.protocol import IngestContext
from app.ingest.sysmon_mapping import MAPPERS, SERVICE_EVENTS, user_section
from app.ingest.sysmon_noise import NoiseFilter
from app.ingest.sysmon_processes import (
    EventFields,
    ProcessLedger,
    ProcessResolver,
    SampleProcesses,
    SampleTree,
    guest_time,
)
from app.ingest.windows_events import WindowsEvent, read_windows_events

SOURCE = "sysmon"
SOURCE_FILE = "sysmon"
EXPORT = ("sysmon", "sysmon.xml")
SUMMARY_LIMIT = 300
SYSMON_SERVICE = "sysmon-service"
UNMAPPED = "unmapped-event"


@dataclass(frozen=True)
class _Kept:
    position: int
    moment: datetime
    event: WindowsEvent
    fields: EventFields


class SysmonNormalizer:
    """The sample's events from the Sysmon export.

    `dropped` counts what the last `normalise` call left out, by reason (`cape-tooling`,
    `windows-background`, `monitor-artefact`, `sysmon-service`, `unmapped-event`); it is complete
    once the iterator is exhausted, and belongs to one ingest at a time.
    """

    source = SOURCE

    def __init__(self) -> None:
        self.dropped: Counter[str] = Counter()

    def normalise(
        self, report: Mapping[str, Any], context: IngestContext
    ) -> Iterator[dict[str, Any]]:
        dropped: Counter[str] = Counter()
        self.dropped = dropped
        if context.analysis_dir is None:
            return
        path = context.analysis_dir.joinpath(*EXPORT)
        offset = guest_clock_offset(report, context.host_registrations)
        sample = SampleProcesses(process.identity for process in read_processes(report, offset))
        ledger = ProcessLedger.read(read_windows_events(path), offset)
        noise = NoiseFilter(SampleTree(sample, ledger), ledger)
        kept = sorted(
            _screened(read_windows_events(path), noise, offset, context.started_at, dropped),
            key=lambda item: (item.moment, item.position),
        )
        resolver = ProcessResolver(sample, ledger, context.analysis_id)
        factory = EventFactory(context, source=SOURCE, source_file=SOURCE_FILE, module=SOURCE)
        for item in kept:
            if (built := _build(factory, resolver, item)) is None:
                dropped[UNMAPPED] += 1
            else:
                yield built


def _screened(
    events: Iterable[WindowsEvent],
    noise: NoiseFilter,
    offset: timedelta,
    fallback: datetime,
    dropped: Counter[str],
) -> Iterator[_Kept]:
    for position, event in enumerate(events):
        if event.event_id in SERVICE_EVENTS:
            dropped[SYSMON_SERVICE] += 1
        elif event.event_id not in MAPPERS:
            dropped[UNMAPPED] += 1
        else:
            fields = EventFields(event.data)
            if reason := noise.reason_to_drop(event.event_id, fields):
                dropped[reason] += 1
                continue
            guest = guest_time(event, fields)
            yield _Kept(position, fallback if guest is None else guest + offset, event, fields)


def _build(factory: EventFactory, resolver: ProcessResolver, item: _Kept) -> dict[str, Any] | None:
    event_id, fields = item.event.event_id, item.fields
    mapped = MAPPERS[event_id](fields)
    if mapped is None:
        return None
    sections = dict(mapped.sections)
    if process := resolver.section(event_id, fields, item.moment):
        sections["process"] = process
    if user := user_section(event_id, fields):
        sections["user"] = user
    raw = {
        "EventID": event_id,
        "EventRecordID": item.event.record_id,
        "EventData": dict(item.event.data),
    }
    return factory.build(
        mapped.shape,
        SourceRecord(item.position, item.moment, raw),
        truncate(mapped.summary, SUMMARY_LIMIT),
        tartarus=mapped.tartarus or None,
        **sections,
    )
