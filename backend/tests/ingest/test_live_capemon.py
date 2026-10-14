"""The live front-end of the capemon rules, against the real logs CAPE built its report from."""

import copy
import json
import random
from collections import Counter
from datetime import UTC, datetime, timedelta
from itertools import groupby
from pathlib import Path
from typing import Any

import pytest

from app.ingest.capemon import CapemonNormalizer
from app.ingest.clock import host_registrations, parse_clock
from app.ingest.ecs import event_id
from app.ingest.live_capemon import LiveCapemon
from app.ingest.protocol import IngestContext
from app.live.bson_log import (
    Argument,
    BsonLogParser,
    CallRecord,
    EnvironRecord,
    LogRecord,
    ProcessRecord,
    ThreadRecord,
    UnknownRecord,
)
from app.live.log_values import clock_text
from tests.ingest.contract import assert_increasing_sequence, assert_unique_ids, check_common_fields

Event = dict[str, Any]
FIXTURES = Path(__file__).parent.parent / "fixtures" / "cape" / "live_logs_45"
HOST_LOG = Path(__file__).parent.parent / "fixtures" / "cape" / "clock" / "task_45.cuckoo.log"
REAL_SKEW = timedelta(seconds=5, milliseconds=297)
PIDS = (9708, 2476)
ANALYSIS_ID = 45
ONE_PER_CALL = 1
EVERYTHING_AT_ONCE = 10**6
FIRST_SEEN = datetime(2026, 10, 13, 13, 39, 50, 393000)
BATCH_SIZES = (ONE_PER_CALL, 7, 50, EVERYTHING_AT_ONCE)


def process_record(
    pid: int,
    *,
    parent_pid: int = 4,
    name: str = "sample.exe",
    first_seen: datetime = FIRST_SEEN,
) -> ProcessRecord:
    return ProcessRecord(
        pid=pid,
        name=name,
        module_path=f"C:\\Temp\\{name}",
        parent_pid=parent_pid,
        first_seen=first_seen,
        first_seen_text=clock_text(first_seen),
    )


def call_record(
    index: int,
    api: str,
    *,
    at: datetime = FIRST_SEEN + timedelta(milliseconds=100),
    **arguments: str,
) -> CallRecord:
    return CallRecord(
        index=index,
        api=api,
        category="misc",
        thread_id=1,
        timestamp=at,
        timestamp_text=clock_text(at),
        caller="0x00000001",
        parent_caller="0x00000002",
        status=True,
        return_value="0x00000000",
        repeated=0,
        arguments=tuple(Argument(name, value, None) for name, value in arguments.items()),
    )


def parse_in_random_chunks(data: bytes, seed: int) -> list[LogRecord]:
    generator = random.Random(seed)  # noqa: S311
    parser, records, position = BsonLogParser(), [], 0
    while position < len(data):
        step = generator.randint(1, 4096)
        records += parser.feed(data[position : position + step])
        position += step
    return records


@pytest.fixture(scope="module")
def records_by_file() -> dict[str, list[LogRecord]]:
    return {
        f"{pid}.bson": parse_in_random_chunks((FIXTURES / f"{pid}.bson").read_bytes(), seed=pid)
        for pid in PIDS
    }


@pytest.fixture(scope="module")
def cape_report(records_by_file: dict[str, list[LogRecord]]) -> dict[str, Any]:
    """The report CAPE built from the logs; the trimmed fixture lacks the `environ` capemon logs."""
    report: dict[str, Any] = json.loads((FIXTURES / "report_calls.json").read_text())
    for entry in report["behavior"]["processes"]:
        [environ] = [
            record
            for record in records_by_file[f"{entry['process_id']}.bson"]
            if isinstance(record, EnvironRecord)
        ]
        entry["environ"] = {"CommandLine": environ.values["CommandLine"]}
    return report


@pytest.fixture(scope="module")
def context(cape_report: dict[str, Any]) -> IngestContext:
    return IngestContext(
        analysis_id=ANALYSIS_ID, started_at=parse_clock(cape_report["info"]["started"])
    )  # type: ignore[arg-type]


@pytest.fixture(scope="module")
def final_events(cape_report: dict[str, Any], context: IngestContext) -> list[Event]:
    return list(CapemonNormalizer().normalise(cape_report, context))


def moment_of(record: LogRecord) -> datetime | None:
    if isinstance(record, ProcessRecord):
        return record.first_seen
    return record.timestamp if isinstance(record, CallRecord) else None


def in_order_of_arrival(
    records_by_file: dict[str, list[LogRecord]],
) -> list[tuple[str, LogRecord]]:
    """Both logs merged by time, each log's own order kept."""
    keyed = []
    for file_number, (file_key, records) in enumerate(records_by_file.items()):
        latest = datetime.min
        for position, record in enumerate(records):
            latest = max(latest, moment_of(record) or latest)
            keyed.append(((latest, file_number, position), file_key, record))
    keyed.sort(key=lambda entry: entry[0])
    return [(file_key, record) for _, file_key, record in keyed]


def feed(live: LiveCapemon, arrivals: list[tuple[str, LogRecord]], batch_size: int) -> list[Event]:
    events: list[Event] = []
    for start in range(0, len(arrivals), batch_size):
        for file_key, run in groupby(arrivals[start : start + batch_size], key=lambda a: a[0]):
            events += live.update(file_key, [record for _, record in run])
    return events


def comparable(event: Event) -> Event:
    """An event without what live is allowed to differ in (see the module under test)."""
    kept = copy.deepcopy(event)
    kept["event"].pop("sequence")
    kept["tartarus"].pop("phase")
    kept["tartarus"].pop("raw")
    kept.get("registry", {}).get("data", {}).pop("type", None)
    return kept


def by_id(events: list[Event]) -> dict[str, Event]:
    return {event["event"]["id"]: comparable(event) for event in events}


# --- equivalence with the final ingest -----------------------------------------------------


@pytest.mark.parametrize("batch_size", BATCH_SIZES)
def test_fed_everything_the_live_path_gives_the_events_of_the_report_path(
    batch_size: int,
    records_by_file: dict[str, list[LogRecord]],
    context: IngestContext,
    final_events: list[Event],
) -> None:
    live = LiveCapemon(context)
    events = feed(live, in_order_of_arrival(records_by_file), batch_size)
    events += live.flush()

    assert len(events) == len(final_events)
    assert by_id(events) == by_id(final_events)


def test_the_real_logs_yield_the_expected_events_per_lane(
    records_by_file: dict[str, list[LogRecord]], context: IngestContext
) -> None:
    live = LiveCapemon(context)
    events = feed(live, in_order_of_arrival(records_by_file), 7) + live.flush()

    assert Counter(event["tartarus"]["lane"] for event in events) == {
        "api": 473,
        "process": 3,
        "file": 2,
        "registry": 2,
        "network": 1,
    }


def test_the_live_events_are_marked_live(
    records_by_file: dict[str, list[LogRecord]], context: IngestContext
) -> None:
    events = feed(LiveCapemon(context), in_order_of_arrival(records_by_file), 7)
    assert {event["tartarus"]["phase"] for event in events} == {"live"}


def test_the_live_raw_is_the_call_as_the_parser_gave_it(
    records_by_file: dict[str, list[LogRecord]], context: IngestContext
) -> None:
    events = feed(LiveCapemon(context), in_order_of_arrival(records_by_file), 7)
    call = next(r for r in records_by_file["9708.bson"] if isinstance(r, CallRecord))
    [raw] = [
        e["tartarus"]["raw"]
        for e in events
        if e["process"]["pid"] == 9708 and e["tartarus"]["raw"]["id"] == call.index
        if e["event"]["action"] == "api-call"
    ]
    assert raw["api"] == call.api
    assert raw["timestamp"] == call.timestamp_text
    assert raw["arguments"] == [{"name": a.name, "value": a.value} for a in call.arguments]


def test_the_only_thing_the_logs_cannot_say_is_the_registry_value_type(
    records_by_file: dict[str, list[LogRecord]],
    context: IngestContext,
    final_events: list[Event],
) -> None:
    live = LiveCapemon(context)
    events = feed(live, in_order_of_arrival(records_by_file), 7) + live.flush()
    live_by_id = {e["event"]["id"]: e for e in events}
    differing = [
        final
        for final in final_events
        if final.get("registry") != live_by_id[final["event"]["id"]].get("registry")
    ]
    assert [e["event"]["action"] for e in differing] == ["reg-value-set"]
    assert differing[0]["registry"]["data"].pop("type") == "REG_SZ"
    assert differing[0]["registry"] == live_by_id[differing[0]["event"]["id"]]["registry"]


# --- order of arrival ----------------------------------------------------------------------


def test_one_file_after_the_other_gives_the_same_events(
    records_by_file: dict[str, list[LogRecord]],
    context: IngestContext,
    final_events: list[Event],
) -> None:
    live = LiveCapemon(context)
    events: list[Event] = []
    for file_key, records in records_by_file.items():
        events += live.update(file_key, records)
    assert by_id(events + live.flush()) == by_id(final_events)


def test_a_process_is_created_once_even_when_two_calls_in_two_batches_create_it(
    records_by_file: dict[str, list[LogRecord]], context: IngestContext
) -> None:
    events = feed(LiveCapemon(context), in_order_of_arrival(records_by_file), ONE_PER_CALL)
    created = [e for e in events if e["event"]["action"] == "process-created"]
    assert [e["process"]["pid"] for e in created] == [2476]


def test_the_creation_of_a_child_waits_for_the_childs_own_log_and_then_names_its_start(
    records_by_file: dict[str, list[LogRecord]], context: IngestContext
) -> None:
    live = LiveCapemon(context)
    parent_records = records_by_file["9708.bson"]
    creation = next(
        i
        for i, r in enumerate(parent_records)
        if isinstance(r, CallRecord) and r.api == "NtCreateUserProcess"
    )
    before_child = live.update("9708.bson", parent_records[: creation + 1])
    assert "process-created" not in {e["event"]["action"] for e in before_child}

    child_records = records_by_file["2476.bson"]
    released = live.update("2476.bson", child_records[:1])
    [created] = released
    assert created["event"]["action"] == "process-created"
    assert created["process"]["entity_id"] == f"{ANALYSIS_ID}:2476@2026-10-13T15:39:51.054Z"


def test_a_child_that_never_logs_is_created_when_flushed_and_only_once(
    context: IngestContext,
) -> None:
    live = LiveCapemon(context)
    creating = call_record(0, "NtCreateUserProcess", ProcessId="200", CommandLine="x.exe /s")
    first = live.update("100.bson", [process_record(100), creating])
    assert [e["event"]["action"] for e in first] == ["api-call"]

    [created] = live.flush()
    assert created["event"]["action"] == "process-created"
    assert created["process"]["entity_id"] == f"{ANALYSIS_ID}:200"
    assert created["process"]["parent"]["pid"] == 100

    again = call_record(1, "CreateProcessInternalW", ProcessId="200", CommandLine="x.exe /s")
    assert [e["event"]["action"] for e in live.update("100.bson", [again])] == ["api-call"]
    assert live.flush() == []


def test_a_child_whose_log_came_first_is_created_at_once(context: IngestContext) -> None:
    live = LiveCapemon(context)
    live.update("200.bson", [process_record(200, parent_pid=100)])
    events = live.update(
        "100.bson",
        [process_record(100), call_record(0, "NtCreateUserProcess", ProcessId="200")],
    )
    assert [e["event"]["action"] for e in events] == ["api-call", "process-created"]
    assert events[1]["process"]["entity_id"].startswith(f"{ANALYSIS_ID}:200@")


# --- what the parser may hand over ---------------------------------------------------------


def test_a_call_whose_process_is_not_known_yet_is_skipped_not_raised(
    context: IngestContext,
) -> None:
    live = LiveCapemon(context)
    assert live.update("100.bson", [call_record(0, "NtClose")]) == []
    assert live.clock_offset is None
    events = live.update("100.bson", [process_record(100), call_record(1, "NtClose")])
    assert [e["process"]["pid"] for e in events] == [100]


def test_records_that_are_not_calls_yield_no_events(context: IngestContext) -> None:
    live = LiveCapemon(context)
    others = [
        process_record(100),
        ThreadRecord(pid=100, thread_id=1),
        EnvironRecord({"CommandLine": "a.exe"}),
        UnknownRecord("call", "no info message", 0, {}),
    ]
    assert live.update("100.bson", others) == []
    assert live.update("100.bson", []) == []


def test_the_command_line_of_the_environ_record_describes_the_process(
    context: IngestContext,
) -> None:
    live = LiveCapemon(context)
    live.update("100.bson", [process_record(100), EnvironRecord({"CommandLine": ' "a.exe" /x '})])
    [event] = live.update("100.bson", [call_record(0, "NtClose")])
    assert event["process"]["command_line"] == '"a.exe" /x'


def test_a_parent_seen_earlier_names_its_children(context: IngestContext) -> None:
    live = LiveCapemon(context)
    live.update("100.bson", [process_record(100, name="parent.exe")])
    live.update("200.bson", [process_record(200, parent_pid=100)])
    [event] = live.update("200.bson", [call_record(0, "NtClose")])
    assert event["process"]["parent"] == {"pid": 100, "name": "parent.exe"}


# --- identity and numbering ----------------------------------------------------------------


def test_event_ids_are_made_of_analysis_source_process_and_place_in_the_process(
    context: IngestContext,
) -> None:
    live = LiveCapemon(context)
    [event] = live.update("100.bson", [process_record(100), call_record(4, "NtClose")])
    assert event["event"]["id"] == event_id(ANALYSIS_ID, "capemon", "processes/100", 4)


def test_sequence_numbers_are_unique_and_rise_across_updates(
    records_by_file: dict[str, list[LogRecord]], context: IngestContext
) -> None:
    events = feed(LiveCapemon(context), in_order_of_arrival(records_by_file), 7)
    assert_increasing_sequence(events)
    assert_unique_ids(events)


def test_live_events_pass_the_common_checks(
    records_by_file: dict[str, list[LogRecord]], context: IngestContext
) -> None:
    live = LiveCapemon(context)
    events = feed(live, in_order_of_arrival(records_by_file), 7) + live.flush()
    assert events
    for event in events:
        check_common_fields(event, context, phase="live")
        json.dumps(event)


# --- the clock -----------------------------------------------------------------------------


def test_the_calibrated_events_land_inside_the_analysis_window(
    records_by_file: dict[str, list[LogRecord]], context: IngestContext, cape_report: dict[str, Any]
) -> None:
    live = LiveCapemon(context)
    events = feed(live, in_order_of_arrival(records_by_file), 7) + live.flush()
    started = context.started_at
    window = (
        started - timedelta(seconds=5),
        started + timedelta(seconds=cape_report["info"]["duration"] + 60),
    )

    assert live.clock_offset == timedelta(hours=2)
    moments = [datetime.fromisoformat(e["@timestamp"]) for e in events]
    assert all(window[0] <= moment <= window[1] for moment in moments)


def test_the_guest_clock_by_itself_is_outside_the_window(
    records_by_file: dict[str, list[LogRecord]], context: IngestContext
) -> None:
    guest_times = [
        record.timestamp.replace(tzinfo=UTC)
        for records in records_by_file.values()
        for record in records
        if isinstance(record, CallRecord)
    ]
    assert all(time < context.started_at - timedelta(seconds=5) for time in guest_times)


def test_the_offset_is_set_by_the_first_process_record_and_kept(context: IngestContext) -> None:
    live = LiveCapemon(context)
    assert live.clock_offset is None
    live.update("100.bson", [process_record(100, first_seen=datetime(2026, 10, 13, 13, 39, 50))])
    assert live.clock_offset == timedelta(hours=2)

    earlier = datetime(2026, 10, 13, 10, 0, 0)
    live.update("200.bson", [process_record(200, first_seen=earlier)])
    [event] = live.update("200.bson", [call_record(0, "NtClose", at=earlier)])
    assert live.clock_offset == timedelta(hours=2)
    assert event["@timestamp"] == "2026-10-13T12:00:00.000Z"


# --- the clock, anchored on the host's log -------------------------------------------------


@pytest.fixture(scope="module")
def anchored_context(context: IngestContext) -> IngestContext:
    return IngestContext(
        context.analysis_id, context.started_at, host_registrations(HOST_LOG.read_text())
    )


@pytest.mark.parametrize("batch_size", BATCH_SIZES)
def test_anchored_on_the_hosts_log_the_live_path_still_gives_the_events_of_the_report_path(
    batch_size: int,
    records_by_file: dict[str, list[LogRecord]],
    cape_report: dict[str, Any],
    anchored_context: IngestContext,
) -> None:
    final = list(CapemonNormalizer().normalise(cape_report, anchored_context))
    live = LiveCapemon(anchored_context)
    events = feed(live, in_order_of_arrival(records_by_file), batch_size) + live.flush()

    assert by_id(events) == by_id(final)


def test_the_anchor_adds_the_skew_to_the_rounded_offset(anchored_context: IngestContext) -> None:
    live = LiveCapemon(anchored_context)
    live.update("100.bson", [process_record(9708, first_seen=FIRST_SEEN)])
    assert live.clock_offset == timedelta(hours=2) + REAL_SKEW


def test_a_first_process_the_log_does_not_know_is_calibrated_to_the_quarter_hour(
    anchored_context: IngestContext,
) -> None:
    live = LiveCapemon(anchored_context)
    live.update("100.bson", [process_record(1234, first_seen=FIRST_SEEN)])
    assert live.clock_offset == timedelta(hours=2)
