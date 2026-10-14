"""The collector's Sigma step: normalise, derive, match, then enqueue."""

from collections.abc import Callable, Iterable
from pathlib import Path

import pytest

from app.live.collector import LiveCollector
from app.live.detections import Detected
from app.rules.loader import load_rules
from app.rules.rule import Rule
from tests.live.collector_support import (
    ANALYSIS_ID,
    POLL_S,
    STARTED_AT,
    Event,
    FakeSink,
    FakeStore,
    append,
    fixture_logs,
    write_in_slices,
)
from tests.live.sigma_support import write_rules
from tests.rules.support import TARTARUS_RULESET

SEEDS = (1, 2, 3)


@pytest.fixture
def logs_dir(tmp_path: Path) -> Path:
    directory = tmp_path / "analyses" / "9" / "logs"
    directory.mkdir(parents=True)
    return directory


@pytest.fixture
def sink() -> FakeSink:
    return FakeSink()


@pytest.fixture
def store() -> FakeStore:
    return FakeStore()


@pytest.fixture
def rules(tmp_path: Path) -> list[Rule]:
    return load_rules(write_rules(tmp_path / "rules"))


def make_collector(
    logs_dir: Path,
    store: FakeStore,
    sink: FakeSink,
    rules: Callable[[], Iterable[Rule]],
) -> LiveCollector:
    return LiveCollector(
        analysis_id=ANALYSIS_ID,
        logs_dir=logs_dir,
        started_at=STARTED_AT,
        store=store,
        sink=sink,
        poll_interval_s=POLL_S,
        rules=lambda: list(rules()),
    )


def alerts_of(events: Iterable[Event]) -> list[Event]:
    return [e for e in events if e.get("rule", {}).get("ruleset") == "sigma"]


async def run_through(
    logs_dir: Path, store: FakeStore, sink: FakeSink, rules: Callable[[], Iterable[Rule]]
) -> None:
    collector = make_collector(logs_dir, store, sink, rules)
    collector.start()
    await write_in_slices(logs_dir, fixture_logs(), seed=1)
    await collector.stop()


async def test_without_rules_no_alert_is_published(
    logs_dir: Path, store: FakeStore, sink: FakeSink
) -> None:
    await run_through(logs_dir, store, sink, lambda: [])

    assert alerts_of(sink.events) == []


@pytest.mark.parametrize("seed", SEEDS)
async def test_an_alert_is_published_in_the_batch_of_the_event_that_triggered_it(
    logs_dir: Path, store: FakeStore, sink: FakeSink, rules: list[Rule], seed: int
) -> None:
    collector = make_collector(logs_dir, store, sink, lambda: rules)
    collector.start()
    await write_in_slices(logs_dir, fixture_logs(), seed=seed)
    await collector.stop()

    alerts = alerts_of(sink.events)
    assert {a["rule"]["name"] for a in alerts} == {"Ver", "Benign file", "Benign key", "Benign dns"}
    for alert in alerts:
        [trigger_id] = alert["related"]["events"]
        [batch] = [b for b in sink.batches if trigger_id in {e["event"]["id"] for e in b}]
        assert alert["event"]["id"] in {e["event"]["id"] for e in batch}


async def test_the_alerts_are_indexed_with_the_other_events(
    logs_dir: Path, store: FakeStore, sink: FakeSink, rules: list[Rule]
) -> None:
    await run_through(logs_dir, store, sink, lambda: rules)

    alerts = alerts_of(sink.events)
    assert alerts
    assert {a["event"]["id"] for a in alerts} <= set(store.documents)


async def test_events_and_alerts_share_one_rising_sequence(
    logs_dir: Path, store: FakeStore, sink: FakeSink, rules: list[Rule]
) -> None:
    await run_through(logs_dir, store, sink, lambda: rules)

    sequences = [event["event"]["sequence"] for event in sink.events]
    assert sequences == sorted(sequences)
    assert len(set(sequences)) == len(sequences)


async def test_the_rules_are_taken_when_the_collector_starts_not_while_it_runs(
    logs_dir: Path, store: FakeStore, sink: FakeSink, rules: list[Rule]
) -> None:
    active: list[Rule] = list(rules)
    collector = make_collector(logs_dir, store, sink, lambda: active)
    active.clear()

    for name, data in fixture_logs().items():
        await append(logs_dir, name, data)
    await collector.stop()

    assert alerts_of(sink.events) != []


async def test_a_repeat_updates_the_index_but_is_not_published_again(
    logs_dir: Path, store: FakeStore, sink: FakeSink, monkeypatch: pytest.MonkeyPatch
) -> None:
    alert = {"event": {"id": "alert-1", "sequence": 0}, "tartarus": {"lane": "process"}}
    update = {**alert, "tartarus": {"lane": "process", "detection": {"repeated": 3}}}
    collector = make_collector(logs_dir, store, sink, lambda: [])
    scripted = iter([Detected([alert], [update])])
    monkeypatch.setattr(
        collector._detections, "process", lambda _events: next(scripted, Detected())
    )

    for name, data in fixture_logs().items():
        await append(logs_dir, name, data)
    await collector.stop()

    assert [e["event"]["id"] for e in sink.events].count("alert-1") == 1
    assert store.documents["alert-1"]["tartarus"]["detection"]["repeated"] == 3


async def test_the_shipped_tartarus_rule_fires_on_the_real_benign_run_while_it_is_collected(
    logs_dir: Path, store: FakeStore, sink: FakeSink
) -> None:
    tartarus_rules = load_rules(TARTARUS_RULESET)

    await run_through(logs_dir, store, sink, lambda: tartarus_rules)

    [alert] = alerts_of(sink.events)
    assert alert["rule"]["name"] == "Tartarus Self-Test Registry Marker Written"
    assert alert["event"]["severity"] == 0
