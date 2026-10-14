from datetime import UTC, datetime
from pathlib import Path

from app.ingest.protocol import IngestContext
from app.live.detections import LiveDetections
from app.rules.loader import load_rule_file
from app.rules.rule import Rule
from tests.rules.support import process_event, rule_yaml, simple_detection

CONTEXT = IngestContext(analysis_id=7, started_at=datetime(2026, 10, 13, 9, 0, tzinfo=UTC))
HIT = "cmd.exe /c evil"


def evil_rule(tmp_path: Path) -> Rule:
    path = tmp_path / "evil.yml"
    path.write_text(
        rule_yaml(simple_detection("CommandLine|contains: evil"), title="Evil"), encoding="utf-8"
    )
    return load_rule_file(path)


def hit(event_id: str, second: int) -> dict[str, object]:
    return process_event(event_id, f"2026-10-13T10:00:{second:02d}.000Z", command_line=HIT)


def test_without_rules_nothing_is_detected() -> None:
    detected = LiveDetections([], CONTEXT).process([hit("a", 1)])

    assert detected.alerts == []
    assert detected.updates == []


def test_a_match_is_a_live_alert_naming_its_trigger(tmp_path: Path) -> None:
    detected = LiveDetections([evil_rule(tmp_path)], CONTEXT).process([hit("a", 1)])

    [alert] = detected.alerts
    assert alert["event"]["kind"] == "alert"
    assert alert["related"]["events"] == ["a"]
    assert alert["tartarus"]["phase"] == "live"
    assert detected.updates == []


def test_a_batch_is_matched_in_event_time_order(tmp_path: Path) -> None:
    detections = LiveDetections([evil_rule(tmp_path)], CONTEXT)

    detected = detections.process([hit("late", 30), hit("early", 5)])

    [alert] = detected.alerts
    assert alert["related"]["events"] == ["early"]
    assert alert["tartarus"]["detection"]["repeated"] == 1


def test_a_repeat_in_a_later_batch_updates_the_alert_it_repeats(tmp_path: Path) -> None:
    detections = LiveDetections([evil_rule(tmp_path)], CONTEXT)
    [first] = detections.process([hit("a", 1)]).alerts

    later = detections.process([hit("b", 10)])

    assert later.alerts == []
    [update] = later.updates
    assert update["event"]["id"] == first["event"]["id"]
    assert update["tartarus"]["detection"]["repeated"] == 1
    assert "repeated" not in first["tartarus"].get("detection", {})


def test_the_update_carries_the_latest_count(tmp_path: Path) -> None:
    detections = LiveDetections([evil_rule(tmp_path)], CONTEXT)
    detections.process([hit("a", 1)])

    detected = detections.process([hit("b", 10), hit("c", 20)])

    [update] = detected.updates
    assert update["tartarus"]["detection"]["repeated"] == 2


def test_an_event_without_a_time_is_not_matched(tmp_path: Path) -> None:
    event = hit("a", 1)
    del event["@timestamp"]

    assert LiveDetections([evil_rule(tmp_path)], CONTEXT).process([event]).alerts == []


def test_a_late_batch_older_than_the_open_window_counts_as_a_repeat(tmp_path: Path) -> None:
    detections = LiveDetections([evil_rule(tmp_path)], CONTEXT)
    [alert] = detections.process([hit("new", 50)]).alerts

    late = detections.process([hit("old", 1)])

    assert late.alerts == []
    [update] = late.updates
    assert update["event"]["id"] == alert["event"]["id"]
