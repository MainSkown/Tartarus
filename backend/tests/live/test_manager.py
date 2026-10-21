import asyncio
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from app.live.hub import LiveFilter, LiveHub
from app.live.manager import LiveCollectionManager
from app.live.messages import EventsMessage, ProcessMessage
from tests.live.collector_support import (
    ANALYSIS_ID,
    POLL_S,
    STARTED_AT,
    FakeStore,
    append,
    by_id,
    fixture_logs,
    reference_events,
    wait_until,
    write_in_slices,
)

TASK_ID = 9


@pytest.fixture
def hub() -> LiveHub:
    return LiveHub()


@pytest.fixture
def store() -> FakeStore:
    return FakeStore()


@pytest.fixture
def manager(tmp_path: Path, hub: LiveHub, store: FakeStore) -> LiveCollectionManager:
    return LiveCollectionManager(
        storage_path=tmp_path, poll_interval_s=POLL_S, store=store, hub=hub
    )


def _make_logs_dir(root: Path, task_id: int) -> Path:
    directory = root / "analyses" / str(task_id) / "logs"
    directory.mkdir(parents=True)
    return directory


@pytest.fixture
def logs_dir(tmp_path: Path) -> Path:
    return _make_logs_dir(tmp_path, TASK_ID)


def events_seen(messages: list) -> list[dict]:  # type: ignore[type-arg]
    return [e for m in messages if isinstance(m, EventsMessage) for e in m.data.events]


async def test_the_logs_of_the_cape_task_reach_the_hub_and_the_index(
    manager: LiveCollectionManager, hub: LiveHub, store: FakeStore, logs_dir: Path
) -> None:
    subscription = hub.subscribe(ANALYSIS_ID, LiveFilter(include_api=True))
    manager.start(ANALYSIS_ID, TASK_ID, STARTED_AT)

    await write_in_slices(logs_dir, fixture_logs(), seed=1)
    await manager.stop(ANALYSIS_ID)

    expected = by_id(reference_events())
    delivered = events_seen(await subscription.next_messages(timeout_s=1.0))
    assert len(delivered) == len(expected)
    assert set(by_id(delivered)) == set(expected)
    assert set(by_id(store.documents.values())) == set(expected)


async def test_starting_twice_runs_one_collector(
    manager: LiveCollectionManager, hub: LiveHub, store: FakeStore, logs_dir: Path
) -> None:
    subscription = hub.subscribe(ANALYSIS_ID, LiveFilter(include_api=True))
    manager.start(ANALYSIS_ID, TASK_ID, STARTED_AT)
    manager.start(ANALYSIS_ID, TASK_ID, STARTED_AT)
    for name, data in fixture_logs().items():
        await append(logs_dir, name, data)

    await manager.stop(ANALYSIS_ID)

    delivered = events_seen(await subscription.next_messages(timeout_s=1.0))
    assert len(delivered) == len(reference_events())


async def test_stopping_the_analysis_ends_its_hub_state_once_nobody_watches(
    manager: LiveCollectionManager, hub: LiveHub
) -> None:
    manager.start(ANALYSIS_ID, TASK_ID, STARTED_AT)
    assert hub.is_tracking(ANALYSIS_ID)

    await manager.stop(ANALYSIS_ID)

    assert not hub.is_tracking(ANALYSIS_ID)


async def test_a_watcher_keeps_the_hub_state_after_the_stop(
    manager: LiveCollectionManager, hub: LiveHub
) -> None:
    manager.start(ANALYSIS_ID, TASK_ID, STARTED_AT)
    watcher = hub.subscribe(ANALYSIS_ID, LiveFilter())

    await manager.stop(ANALYSIS_ID)
    assert hub.is_tracking(ANALYSIS_ID)
    watcher.close()

    assert not hub.is_tracking(ANALYSIS_ID)


async def test_stopping_an_analysis_that_is_not_collected_is_harmless(
    manager: LiveCollectionManager,
) -> None:
    await manager.stop(12345)


async def test_a_start_time_without_a_zone_is_taken_as_utc(
    manager: LiveCollectionManager, hub: LiveHub, logs_dir: Path
) -> None:
    subscription = hub.subscribe(ANALYSIS_ID, LiveFilter(include_api=True))
    naive = STARTED_AT.astimezone(UTC).replace(tzinfo=None)
    manager.start(ANALYSIS_ID, TASK_ID, naive)
    for name, data in fixture_logs().items():
        await append(logs_dir, name, data)

    await manager.stop(ANALYSIS_ID)

    assert len(events_seen(await subscription.next_messages(timeout_s=1.0))) == len(
        reference_events()
    )


async def test_closing_the_manager_stops_every_collector(
    manager: LiveCollectionManager, hub: LiveHub, logs_dir: Path
) -> None:
    manager.start(ANALYSIS_ID, TASK_ID, STARTED_AT)
    manager.start(ANALYSIS_ID + 1, TASK_ID + 1, STARTED_AT)
    for name, data in fixture_logs().items():
        await append(logs_dir, name, data)

    await manager.aclose()

    assert not hub.is_tracking(ANALYSIS_ID)
    assert not hub.is_tracking(ANALYSIS_ID + 1)


async def test_the_collector_idles_while_cape_has_not_created_the_logs(
    manager: LiveCollectionManager, hub: LiveHub, tmp_path: Path
) -> None:
    manager.start(ANALYSIS_ID, TASK_ID + 5, datetime(2026, 10, 13, tzinfo=UTC))
    await asyncio.sleep(POLL_S * 5)

    await manager.stop(ANALYSIS_ID)

    assert not hub.is_tracking(ANALYSIS_ID)


class PerAnalysisStore:
    """An event store keyed by analysis and then event id, so two analyses can share event ids."""

    def __init__(self) -> None:
        self.documents: dict[int, dict[str, dict[str, Any]]] = {}

    async def ensure_template(self) -> None:
        return None

    async def ensure_index(self, analysis_id: int) -> None:
        self.documents.setdefault(analysis_id, {})

    async def bulk_index(self, analysis_id: int, events: Iterable[dict[str, Any]]) -> int:
        batch = list(events)
        for event in batch:
            self.documents.setdefault(analysis_id, {})[event["event"]["id"]] = event
        return len(batch)

    def indexed_ids(self, analysis_id: int) -> set[str]:
        return set(self.documents.get(analysis_id, {}))


def _process_pids(messages: list) -> set[int]:  # type: ignore[type-arg]
    return {m.data.node.pid for m in messages if isinstance(m, ProcessMessage)}


def _delivered_ids(messages: list) -> list[str]:  # type: ignore[type-arg]
    return [
        e["event"]["id"] for m in messages if isinstance(m, EventsMessage) for e in m.data.events
    ]


async def test_two_collectors_stream_their_own_logs_and_stopping_one_leaves_the_other_running(
    tmp_path: Path,
) -> None:
    first_id, second_id = ANALYSIS_ID, ANALYSIS_ID + 1
    first_task, second_task = TASK_ID, TASK_ID + 1
    first_dir = _make_logs_dir(tmp_path, first_task)
    second_dir = _make_logs_dir(tmp_path, second_task)
    first_logs = fixture_logs()
    first_name, second_name = "9708.bson", "2476.bson"
    second_logs = {second_name: first_logs[second_name]}
    cut = len(second_logs[second_name]) // 2
    second_first_half = {second_name: second_logs[second_name][:cut]}
    second_second_half = {second_name: second_logs[second_name][cut:]}
    expected_first = by_id(reference_events(first_logs, first_id))
    expected_second = by_id(reference_events(second_logs, second_id))
    assert len(expected_second) < len(expected_first)

    hub = LiveHub(queue_bound=100_000)
    store = PerAnalysisStore()
    manager = LiveCollectionManager(
        storage_path=tmp_path, poll_interval_s=POLL_S, store=store, hub=hub
    )
    first_watch = hub.subscribe(first_id, LiveFilter(include_api=True))
    second_watch = hub.subscribe(second_id, LiveFilter(include_api=True))
    manager.start(first_id, first_task, STARTED_AT)
    manager.start(second_id, second_task, STARTED_AT)

    await asyncio.gather(
        write_in_slices(first_dir, first_logs, seed=1),
        write_in_slices(second_dir, second_first_half, seed=2),
    )
    await manager.stop(first_id)
    first_messages = first_watch.flush()

    await append(first_dir, "late-copy.bson", first_logs[first_name])
    indexed_before_second_half = len(store.indexed_ids(second_id))
    await write_in_slices(second_dir, second_second_half, seed=3)
    await wait_until(lambda: len(store.indexed_ids(second_id)) > indexed_before_second_half)
    await manager.stop(second_id)

    second_messages = second_watch.flush()
    assert sorted(_delivered_ids(first_messages)) == sorted(expected_first)
    assert _delivered_ids(first_watch.flush()) == []
    assert sorted(_delivered_ids(second_messages)) == sorted(expected_second)
    assert _process_pids(first_messages) == {2476, 9708}
    assert _process_pids(second_messages) == {2476}
    assert store.indexed_ids(first_id) == set(expected_first)
    assert store.indexed_ids(second_id) == set(expected_second)
