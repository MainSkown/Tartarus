import time
from datetime import UTC, datetime, timedelta
from typing import Any

from app.ingest.protocol import IngestContext
from app.rules.engine import Emit, Repeat, SigmaEngine
from app.rules.matcher import RuleMatcher
from tests.rules.test_shipped_rules import build_event, firing_fields, shipped_rules

EVENT_COUNT = 20_000
TIME_LIMIT_SECONDS = 2.0  # measured at about 0.05 s; generous so a slow CI runner does not flake
START = datetime(2026, 10, 13, 10, 0, tzinfo=UTC)


def stream() -> tuple[list[dict[str, Any]], int]:
    """20 000 events (70% `api-call`, 20% benign Sigma-category, 10% matching) and the number of
    rule matches they hold, counted once per distinct matching event."""
    rules = shipped_rules()
    matching = [build_event(rule, firing_fields(rule)) for rule in rules]
    matches_of = [len(RuleMatcher(rules).match(document)) for document in matching]
    assert all(count >= 1 for count in matches_of)
    benign_process = build_event(rules[-1], {"process.executable": "C:\\Windows\\notepad.exe"})
    benign_process["event"]["action"] = "process-created"
    benign_file = build_event(rules[0], {"file.path": "C:\\Users\\a\\notes.txt"})
    benign_file["event"]["action"] = "file-created"
    expected = 0
    events: list[dict[str, Any]] = []
    for number in range(EVENT_COUNT):
        slot = number % 10
        if slot < 7:
            document: dict[str, Any] = {
                "event": {"action": "api-call", "kind": "event"},
                "api": {"name": "NtClose"},
            }
        elif slot < 9:
            document = dict(benign_process if slot == 7 else benign_file)
        else:
            index = (number // 10) % len(matching)
            document = dict(matching[index])
            expected += matches_of[index]
        document["@timestamp"] = (START + timedelta(milliseconds=10 * number)).isoformat()
        document["event"] = {**document["event"], "id": f"evt-{number}"}
        events.append(document)
    return events, expected


def test_all_shipped_rules_over_twenty_thousand_events_are_fast_and_find_every_match() -> None:
    events, expected = stream()
    matcher = RuleMatcher(shipped_rules())

    started = time.perf_counter()
    found = sum(len(matcher.match(event)) for event in events)
    elapsed = time.perf_counter() - started

    assert expected >= 2000
    assert found == expected
    assert elapsed < TIME_LIMIT_SECONDS


def test_the_engine_with_suppression_and_alert_building_is_fast_too() -> None:
    events, expected = stream()
    engine = SigmaEngine(shipped_rules(), IngestContext(7, START))

    started = time.perf_counter()
    outcomes = [outcome for event in events for outcome in engine.process(event)]
    elapsed = time.perf_counter() - started

    emitted = sum(isinstance(outcome, Emit) for outcome in outcomes)
    repeated = sum(isinstance(outcome, Repeat) for outcome in outcomes)
    assert emitted + repeated == expected
    assert emitted >= 60
    assert repeated > 0
    assert elapsed < TIME_LIMIT_SECONDS
