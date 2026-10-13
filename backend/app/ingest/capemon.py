from collections.abc import Iterator, Mapping
from typing import Any

from app.ingest.capemon_calls import (
    Call,
    CapemonProcess,
    calls_in_sequence_order,
    read_processes,
)
from app.ingest.capemon_rules import DerivationRun, Derived, derive
from app.ingest.clock import guest_clock_offset
from app.ingest.ecs import (
    EventFactory,
    EventShape,
    SourceRecord,
    event_id,
    process_fields,
    related_events,
)
from app.ingest.protocol import IngestContext

SOURCE = "capemon"
SOURCE_FILE = "report.json"
DERIVED_SOURCE_FILE = "report.json#derived"

API_CATEGORY_TO_ECS = {
    "filesystem": "file",
    "registry": "registry",
    "network": "network",
    "process": "process",
    "threading": "process",
}
FALLBACK_ECS_CATEGORY = "host"
API_SHAPES = {
    ecs_category: EventShape("api-call", (ecs_category,), ("info",), "api", "capemon.api")
    for ecs_category in {*API_CATEGORY_TO_ECS.values(), FALLBACK_ECS_CATEGORY}
}


def _read(
    report: Mapping[str, Any], context: IngestContext
) -> tuple[list[CapemonProcess], list[Call]]:
    clock_offset = guest_clock_offset(report)
    processes = read_processes(report, clock_offset)
    return processes, calls_in_sequence_order(processes, clock_offset, context.started_at)


def read_calls(report: Mapping[str, Any], context: IngestContext) -> list[Call]:
    """The report's calls on the UTC clock, in the order the events are emitted."""
    return _read(report, context)[1]


def api_event_id(analysis_id: int, call: Call) -> str:
    return event_id(analysis_id, SOURCE, SOURCE_FILE, call.index)


def call_lane(call: Call) -> str:
    """The semantic lane a call belongs to; the `api` lane only holds the raw call events."""
    return API_CATEGORY_TO_ECS.get(call.category or "", "process")


class CapemonNormalizer:
    """Turns the calls of `behavior.processes` into `api` events and the events derived from them.

    Derivation rules: docs/specs/data-model.md, "capemon derivation rules (as built)".
    """

    source = SOURCE

    def normalise(
        self, report: Mapping[str, Any], context: IngestContext
    ) -> Iterator[dict[str, Any]]:
        processes, calls = _read(report, context)
        run = DerivationRun({process.identity.pid: process.identity for process in processes})
        factory = EventFactory(context, source=SOURCE, source_file=SOURCE_FILE, module=SOURCE)
        for call in calls:
            api_event = _api_event(factory, call, context.analysis_id)
            yield api_event
            derived = derive(call, run)
            if derived is not None:
                yield _derived_event(factory, call, derived, api_event, context.analysis_id)


def _api_fields(call: Call) -> dict[str, Any]:
    fields: dict[str, Any] = {"name": call.api, "arguments": dict(call.arguments)}
    optional = {
        "category": call.category,
        "status": call.status,
        "return_value": call.return_value,
        "repeated": call.repeated,
    }
    return fields | {key: value for key, value in optional.items() if value is not None}


def _owner_process(call: Call, analysis_id: int) -> dict[str, Any]:
    return process_fields(call.process, analysis_id, thread_id=call.thread_id)


def _api_event(factory: EventFactory, call: Call, analysis_id: int) -> dict[str, Any]:
    shape = API_SHAPES[API_CATEGORY_TO_ECS.get(call.category or "", FALLBACK_ECS_CATEGORY)]
    record = SourceRecord(call.index, call.timestamp, call.raw)
    return factory.build(
        shape,
        record,
        f"{call.label} called {call.api}",
        process=_owner_process(call, analysis_id),
        api=_api_fields(call),
    )


def _derived_event(
    factory: EventFactory,
    call: Call,
    derived: Derived,
    api_event: Mapping[str, Any],
    analysis_id: int,
) -> dict[str, Any]:
    record = SourceRecord(call.index, call.timestamp, call.raw, source_file=DERIVED_SOURCE_FILE)
    process = (
        process_fields(derived.process, analysis_id)
        if derived.process
        else _owner_process(call, analysis_id)
    )
    sections = {
        "process": process,
        **derived.sections,
        "related": related_events(api_event["event"]["id"]),
    }
    return factory.build(
        derived.shape, record, derived.summary, tartarus=derived.tartarus, **sections
    )
