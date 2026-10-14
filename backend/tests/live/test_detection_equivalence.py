"""Live and final detections agree: same alerts by id, rule, trigger and repeat count.

The final ingest is authoritative (it sorts the whole event set); these tests pin that the
live path, however its batches fall, reaches the same alerts when events arrive in time order
per process, which is how a log is written.
"""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app.ingest.capemon import CapemonNormalizer
from app.ingest.ingester import ReportIngester
from app.ingest.protocol import IngestContext
from app.ingest.sigma import final_detections
from app.live.collector import LiveCollector
from app.live.detections import LiveDetections
from app.rules.loader import load_rules
from app.rules.rule import Rule
from tests.ingest.fake_index import FakeIndex
from tests.live.collector_support import (
    ANALYSIS_ID,
    POLL_S,
    STARTED_AT,
    Event,
    FakeSink,
    FakeStore,
    fixture_logs,
    write_final_report,
    write_in_slices,
)
from tests.live.sigma_support import FIXTURE_RULES, write_rules
from tests.rules.support import process_event, rule_yaml, simple_detection

SEEDS = (1, 2, 3, 4)
BATCH_SIZES = (1, 3, 7, 1000)


def sigma_alerts(events: list[Event]) -> list[Event]:
    return [e for e in events if e.get("rule", {}).get("ruleset") == "sigma"]


def as_comparable(alert: Event) -> Event:
    """An alert minus what live may differ in: the sequence, the phase, and the parent's name,
    which only shows once the parent's own log has been read."""
    process = alert.get("process", {})
    parent = {k: v for k, v in process.get("parent", {}).items() if k != "name"}
    return {
        **alert,
        "event": {k: v for k, v in alert["event"].items() if k != "sequence"},
        "tartarus": {k: v for k, v in alert["tartarus"].items() if k != "phase"},
        "process": {**process, "parent": parent},
    }


def by_id(alerts: list[Event]) -> dict[str, Event]:
    return {alert["event"]["id"]: as_comparable(alert) for alert in alerts}


@pytest.fixture
def rules(tmp_path: Path) -> list[Rule]:
    return load_rules(write_rules(tmp_path / "rules"))


async def final_alerts_of_the_fixture_run(tmp_path: Path, rules: list[Rule]) -> list[Event]:
    index = FakeIndex()
    ingester = ReportIngester(index, [CapemonNormalizer()], rules=lambda: rules)
    await ingester.ingest(ANALYSIS_ID, write_final_report(tmp_path))
    return sigma_alerts(index.events)


@pytest.mark.parametrize("seed", SEEDS)
async def test_the_collector_and_the_final_ingest_raise_the_same_alerts(
    tmp_path: Path, rules: list[Rule], seed: int
) -> None:
    logs_dir = tmp_path / "logs"
    logs_dir.mkdir()
    store, sink = FakeStore(), FakeSink()
    collector = LiveCollector(
        analysis_id=ANALYSIS_ID,
        logs_dir=logs_dir,
        started_at=STARTED_AT,
        store=store,
        sink=sink,
        poll_interval_s=POLL_S,
        rules=lambda: rules,
    )
    collector.start()
    await write_in_slices(logs_dir, fixture_logs(), seed)
    await collector.stop()

    live = sigma_alerts(sink.events)
    final = await final_alerts_of_the_fixture_run(tmp_path, rules)

    assert len(final) == len(FIXTURE_RULES)
    assert by_id(live) == by_id(final)
    assert by_id(sigma_alerts(list(store.documents.values()))) == by_id(final)


# --- repeats: the fixture run has none, so a synthetic stream carries them ---------------------

CONTEXT = IngestContext(analysis_id=7, started_at=datetime(2026, 10, 13, 9, 0, tzinfo=UTC))
FIRST = datetime(2026, 10, 13, 10, 0, 0, tzinfo=UTC)
ENTITY_A = "7:100@2026-10-13T09:59:00.000Z"
ENTITY_B = "7:200@2026-10-13T09:59:30.000Z"
# (entity, seconds after FIRST, command line): A repeats twice then opens a second window
# at 70 s; B interleaves with it and has one event that matches nothing.
STREAM = (
    (ENTITY_A, 1, "evil.exe"),
    (ENTITY_B, 2, "evil.exe"),
    (ENTITY_A, 10, "evil.exe"),
    (ENTITY_B, 12, "fine.exe"),
    (ENTITY_A, 20, "evil.exe"),
    (ENTITY_B, 30, "evil.exe"),
    (ENTITY_A, 70, "evil.exe"),
    (ENTITY_A, 75, "evil.exe"),
    (ENTITY_B, 100, "evil.exe"),
)


@pytest.fixture
def evil_rule(tmp_path: Path) -> Rule:
    [rule] = load_rules(_write(tmp_path, "CommandLine|contains: evil"))
    return rule


def _write(tmp_path: Path, selection: str) -> Path:
    directory = tmp_path / "synthetic"
    directory.mkdir()
    (directory / "rule.yml").write_text(
        rule_yaml(simple_detection(selection), title="Evil"), encoding="utf-8"
    )
    return directory


def stream_events() -> list[Event]:
    return [
        process_event(
            f"event-{number}",
            (FIRST + timedelta(seconds=second)).isoformat(timespec="milliseconds"),
            entity_id=entity,
            command_line=command_line,
        )
        for number, (entity, second, command_line) in enumerate(STREAM)
    ]


def indexed_state(batches: list[list[Event]], rule: Rule) -> list[Event]:
    """The alerts as the index holds them after every batch: later writes replace earlier."""
    detections = LiveDetections([rule], CONTEXT)
    held: dict[str, Event] = {}
    for batch in batches:
        detected = detections.process(batch)
        for alert in [*detected.alerts, *detected.updates]:
            held[alert["event"]["id"]] = alert
    return list(held.values())


@pytest.mark.parametrize("size", BATCH_SIZES)
def test_live_batches_of_any_size_end_with_the_final_alerts_and_repeat_counts(
    evil_rule: Rule, size: int
) -> None:
    events = stream_events()
    batches = [events[start : start + size] for start in range(0, len(events), size)]

    live = indexed_state(batches, evil_rule)

    final = final_detections([evil_rule], CONTEXT, events)
    assert len(final) == 4
    repeats = sorted(a["tartarus"]["detection"].get("repeated", 0) for a in final)
    assert repeats == [0, 1, 1, 2]
    assert by_id(live) == by_id(final)
