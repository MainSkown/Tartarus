import asyncio
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.live.hub import LiveFilter, LiveHub
from app.live.manager import LiveCollectionManager
from app.live.messages import EventsMessage
from tests.live.collector_support import (
    ANALYSIS_ID,
    POLL_S,
    STARTED_AT,
    FakeStore,
    append,
    by_id,
    fixture_logs,
    reference_events,
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


@pytest.fixture
def logs_dir(tmp_path: Path) -> Path:
    directory = tmp_path / "analyses" / str(TASK_ID) / "logs"
    directory.mkdir(parents=True)
    return directory


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
