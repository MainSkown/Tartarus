import asyncio
import logging
import struct
from collections import defaultdict
from pathlib import Path

import pytest

from app.live.collector import LiveCollector
from tests.live.bson_encode import encode_document
from tests.live.collector_support import (
    ANALYSIS_ID,
    POLL_S,
    STARTED_AT,
    FakeSink,
    FakeStore,
    append,
    by_id,
    fixture_logs,
    reference_events,
    wait_for_quiet,
    wait_until,
    write_in_slices,
)

SEEDS = (1, 2, 3)
THREE_BYTES = 3


@pytest.fixture
def missing_logs_dir(tmp_path: Path) -> Path:
    return tmp_path / "analyses" / "9" / "logs"


@pytest.fixture
def logs_dir(missing_logs_dir: Path) -> Path:
    missing_logs_dir.mkdir(parents=True)
    return missing_logs_dir


@pytest.fixture
def sink() -> FakeSink:
    return FakeSink()


@pytest.fixture
def store() -> FakeStore:
    return FakeStore()


def make_collector(
    logs_dir: Path, store: FakeStore, sink: FakeSink, poll_interval_s: float = POLL_S
) -> LiveCollector:
    return LiveCollector(
        analysis_id=ANALYSIS_ID,
        logs_dir=logs_dir,
        started_at=STARTED_AT,
        store=store,
        sink=sink,
        poll_interval_s=poll_interval_s,
    )


def api_call_ids_per_pid(sink: FakeSink) -> dict[int, list[int]]:
    ids: dict[int, list[int]] = defaultdict(list)
    for event in sink.events:
        if event["tartarus"]["lane"] == "api":
            ids[event["process"]["pid"]].append(event["tartarus"]["raw"]["id"])
    return ids


@pytest.mark.parametrize("seed", SEEDS)
async def test_logs_written_in_random_slices_give_the_events_of_the_whole_files(
    logs_dir: Path, store: FakeStore, sink: FakeSink, seed: int
) -> None:
    collector = make_collector(logs_dir, store, sink)
    collector.start()

    await write_in_slices(logs_dir, fixture_logs(), seed)
    await collector.stop()

    expected = reference_events()
    published_ids = [event["event"]["id"] for event in sink.events]
    assert len(published_ids) == len(set(published_ids))
    assert by_id(sink.events) == by_id(expected)
    assert len(sink.events) == len(expected)


@pytest.mark.parametrize("seed", SEEDS)
async def test_events_arrive_in_the_order_the_calls_were_logged(
    logs_dir: Path, store: FakeStore, sink: FakeSink, seed: int
) -> None:
    collector = make_collector(logs_dir, store, sink)
    collector.start()

    await write_in_slices(logs_dir, fixture_logs(), seed)
    await collector.stop()

    sequences = [event["event"]["sequence"] for event in sink.events]
    assert sequences == sorted(sequences)
    assert len(set(sequences)) == len(sequences)
    for call_ids in api_call_ids_per_pid(sink).values():
        assert call_ids == sorted(call_ids)


async def test_the_events_are_indexed_into_the_analysis_index_by_id(
    logs_dir: Path, store: FakeStore, sink: FakeSink
) -> None:
    collector = make_collector(logs_dir, store, sink)
    collector.start()

    await write_in_slices(logs_dir, fixture_logs(), seed=5)
    await collector.stop()

    assert store.templates >= 1
    assert store.indexes_ensured >= 1
    assert store.documents == {event["event"]["id"]: event for event in sink.events}
    assert by_id(store.documents.values()) == by_id(reference_events())


async def test_a_record_cut_in_half_waits_for_its_remaining_bytes(
    logs_dir: Path, store: FakeStore, sink: FakeSink
) -> None:
    logs = fixture_logs()
    whole = len(reference_events())
    last = max(logs)
    for name, data in logs.items():
        await append(logs_dir, name, data[:-THREE_BYTES] if name == last else data)
    collector = make_collector(logs_dir, store, sink)
    collector.start()
    await wait_until(lambda: bool(sink.events))
    await wait_for_quiet(sink)

    held_back = len(sink.events)
    await append(logs_dir, last, logs[last][-THREE_BYTES:])
    await collector.stop()

    assert 0 < held_back < whole
    assert by_id(sink.events) == by_id(reference_events())


async def test_stopping_drains_what_was_written_since_the_last_poll(
    logs_dir: Path, store: FakeStore, sink: FakeSink
) -> None:
    collector = make_collector(logs_dir, store, sink, poll_interval_s=60.0)
    collector.start()
    await asyncio.sleep(0.05)
    for name, data in fixture_logs().items():
        await append(logs_dir, name, data)

    await collector.stop()

    assert by_id(sink.events) == by_id(reference_events())
    assert by_id(store.documents.values()) == by_id(reference_events())


async def test_stopping_releases_the_creations_whose_child_never_logged(
    logs_dir: Path, store: FakeStore, sink: FakeSink
) -> None:
    logs = fixture_logs()
    parent = "9708.bson"
    await append(logs_dir, parent, logs[parent])
    collector = make_collector(logs_dir, store, sink, poll_interval_s=60.0)
    collector.start()
    await asyncio.sleep(0.05)

    await collector.stop()

    created = [e for e in sink.events if e["event"]["action"] == "process-created"]
    assert len(created) == 1


async def test_stop_is_idempotent_and_the_collector_publishes_nothing_afterwards(
    logs_dir: Path, store: FakeStore, sink: FakeSink
) -> None:
    collector = make_collector(logs_dir, store, sink)
    collector.start()
    await write_in_slices(logs_dir, fixture_logs(), seed=1)

    await collector.stop()
    published = len(sink.events)
    await collector.stop()
    await asyncio.sleep(POLL_S * 5)

    assert len(sink.events) == published


async def test_a_collector_stopped_before_it_ever_ran_still_drains_once(
    logs_dir: Path, store: FakeStore, sink: FakeSink
) -> None:
    for name, data in fixture_logs().items():
        await append(logs_dir, name, data)

    await make_collector(logs_dir, store, sink).stop()

    assert by_id(sink.events) == by_id(reference_events())


async def test_a_logs_directory_that_appears_late_is_picked_up(
    missing_logs_dir: Path, store: FakeStore, sink: FakeSink
) -> None:
    logs_dir = missing_logs_dir
    collector = make_collector(logs_dir, store, sink)
    collector.start()
    await asyncio.sleep(POLL_S * 10)
    assert sink.events == []

    await asyncio.to_thread(logs_dir.mkdir, parents=True)
    await write_in_slices(logs_dir, fixture_logs(), seed=2)
    await collector.stop()

    assert by_id(sink.events) == by_id(reference_events())


async def test_a_logs_directory_that_never_appears_leaves_the_collector_idle(
    missing_logs_dir: Path, store: FakeStore, sink: FakeSink
) -> None:
    collector = make_collector(missing_logs_dir, store, sink)
    collector.start()
    await asyncio.sleep(POLL_S * 10)

    await collector.stop()

    assert (sink.events, sink.errors, store.bulk_calls) == ([], [], 0)


async def test_files_that_are_not_bson_logs_are_ignored(
    logs_dir: Path, store: FakeStore, sink: FakeSink
) -> None:
    await append(logs_dir, "notes.txt", b"not a log")
    await append(logs_dir, "tlsdump.log", b"\xff\xff\xff\xff")

    await make_collector(logs_dir, store, sink).stop()

    assert (sink.events, sink.errors) == ([], [])


async def test_a_broken_log_is_reported_and_dropped_while_the_other_logs_carry_on(
    logs_dir: Path, store: FakeStore, sink: FakeSink
) -> None:
    await append(logs_dir, "1111.bson", struct.pack("<I", 3) + b"\x00" * 10)
    collector = make_collector(logs_dir, store, sink)
    collector.start()
    await wait_until(lambda: sink.errors != [])

    await write_in_slices(logs_dir, fixture_logs(), seed=4)
    await append(logs_dir, "1111.bson", b"more garbage after the failure")
    await collector.stop()

    assert sink.error_codes() == ["log_format"]
    assert "1111.bson" in sink.errors[0][1]
    assert by_id(sink.events) == by_id(reference_events())


async def test_the_records_parsed_before_a_log_broke_are_not_lost(
    logs_dir: Path, store: FakeStore, sink: FakeSink
) -> None:
    data = fixture_logs()["9708.bson"]
    await append(logs_dir, "9708.bson", data + struct.pack("<I", 3) + b"\x00" * 10)
    await append(logs_dir, "2476.bson", fixture_logs()["2476.bson"])

    await make_collector(logs_dir, store, sink).stop()

    assert sink.error_codes() == ["log_format"]
    assert by_id(sink.events) == by_id(reference_events())


async def test_unknown_records_are_logged_with_their_kind_without_stopping_anything(
    logs_dir: Path, store: FakeStore, sink: FakeSink, caplog: pytest.LogCaptureFixture
) -> None:
    oddities = b"".join(encode_document({"type": "debug", "msg": str(n)}) for n in range(250))
    logs = fixture_logs()
    await append(logs_dir, "9708.bson", logs["9708.bson"] + oddities)
    await append(logs_dir, "2476.bson", logs["2476.bson"])

    with caplog.at_level(logging.WARNING, logger="app.live.collector"):
        await make_collector(logs_dir, store, sink).stop()

    warnings = [r for r in caplog.records if r.levelno == logging.WARNING and "debug" in r.message]
    assert 1 <= len(warnings) <= 5
    assert by_id(sink.events) == by_id(reference_events())
    assert sink.errors == []


async def test_a_restarted_collector_reads_everything_again_and_the_index_has_no_duplicates(
    logs_dir: Path, store: FakeStore, sink: FakeSink
) -> None:
    logs = fixture_logs()
    first = make_collector(logs_dir, store, sink)
    first.start()
    half = {name: data[: len(data) // 2] for name, data in logs.items()}
    await write_in_slices(logs_dir, half, seed=6)
    await first.stop()
    assert 0 < len(store.documents) < len(reference_events())

    for name, data in logs.items():
        await append(logs_dir, name, data[len(data) // 2 :])
    second_sink = FakeSink()
    second = make_collector(logs_dir, store, second_sink)
    second.start()
    await second.stop()

    assert by_id(store.documents.values()) == by_id(reference_events())
    assert len(store.documents) == len(reference_events())
    assert by_id(second_sink.events) == by_id(reference_events())


async def test_a_failing_index_does_not_stop_publication_and_is_reported_once(
    logs_dir: Path, store: FakeStore, sink: FakeSink
) -> None:
    store.failures_left = 10**6
    collector = make_collector(logs_dir, store, sink)
    collector.start()

    await write_in_slices(logs_dir, fixture_logs(), seed=7)
    await collector.stop()

    assert by_id(sink.events) == by_id(reference_events())
    assert sink.error_codes() == ["live_index_failed"]
    assert store.bulk_calls > 1


async def test_indexing_resumes_after_a_failure_without_reporting_again(
    logs_dir: Path, store: FakeStore, sink: FakeSink
) -> None:
    store.failures_left = 1
    collector = make_collector(logs_dir, store, sink)
    collector.start()

    await write_in_slices(logs_dir, fixture_logs(), seed=8)
    await collector.stop()

    assert sink.error_codes() == ["live_index_failed"]
    assert 0 < len(store.documents) <= len(reference_events())


async def test_a_failing_template_is_reported_as_an_index_failure_too(
    logs_dir: Path, sink: FakeSink
) -> None:
    class NoTemplate(FakeStore):
        async def ensure_template(self) -> None:
            raise ConnectionError("opensearch is down")

    for name, data in fixture_logs().items():
        await append(logs_dir, name, data)

    await make_collector(logs_dir, NoTemplate(), sink).stop()

    assert sink.error_codes() == ["live_index_failed"]
    assert by_id(sink.events) == by_id(reference_events())


async def test_a_log_that_cannot_be_read_does_not_stop_the_others(
    logs_dir: Path, store: FakeStore, sink: FakeSink
) -> None:
    await asyncio.to_thread((logs_dir / "0.bson").mkdir)
    collector = make_collector(logs_dir, store, sink)
    collector.start()

    await write_in_slices(logs_dir, fixture_logs(), seed=9)
    await collector.stop()

    assert by_id(sink.events) == by_id(reference_events())
