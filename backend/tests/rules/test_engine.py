import copy
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from app.ingest.protocol import IngestContext
from app.rules.engine import Emit, Repeat, SigmaEngine, apply_repeats
from app.rules.loader import load_rule_file
from app.rules.predicate import Event
from app.rules.rule import Rule
from tests.rules.support import DEFAULT_ID, process_event, rule_yaml, simple_detection
from tests.rules.test_matcher import fake_rule

CONTEXT = IngestContext(analysis_id=7, started_at=datetime(2026, 10, 13, 9, 0, tzinfo=UTC))
OTHER_ID = "0b1c2d3e-0000-4000-8000-000000000001"
START = datetime(2026, 10, 13, 10, 0, 0, tzinfo=UTC)


def make_rule(  # noqa: PLR0913 - one keyword per field a test may vary
    tmp_path: Path,
    *,
    rule_id: str = DEFAULT_ID,
    level: str | None = "high",
    tags: tuple[str, ...] = (),
    needle: str = "evil",
    name: str = "rule.yml",
    author: str | None = None,
) -> Rule:
    text = rule_yaml(
        simple_detection(f"CommandLine|contains: {needle}"),
        rule_id=rule_id,
        level=level,
        tags=tags,
        title="Evil command line",
        extra=f"author: {author}" if author else "",
    )
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return load_rule_file(path)


def at(seconds: float) -> str:
    moment = START + timedelta(seconds=seconds)
    return moment.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def hit(event_id: str, seconds: float, **kwargs: Any) -> dict[str, object]:
    return process_event(event_id, at(seconds), command_line="run evil.exe", **kwargs)


def engine_for(*rules: Rule, phase: str = "final") -> SigmaEngine:
    return SigmaEngine(rules, CONTEXT, phase=phase)  # type: ignore[arg-type]


def feed(engine: SigmaEngine, events: list[dict[str, object]]) -> list[Emit | Repeat]:
    return [outcome for event in events for outcome in engine.process(event)]


class TestTheEmittedAlert:
    def test_a_match_is_an_alert_event_with_the_rules_identity(self, tmp_path: Path) -> None:
        rule = make_rule(tmp_path, tags=("attack.execution", "attack.t1059.001"))

        [outcome] = engine_for(rule).process(hit("evt-1", 0))

        assert isinstance(outcome, Emit)
        alert = outcome.detection
        assert alert["event"]["kind"] == "alert"
        assert alert["event"]["module"] == "sigma"
        assert alert["rule"]["ruleset"] == "sigma"
        assert alert["rule"]["id"] == DEFAULT_ID
        assert alert["rule"]["name"] == "Evil command line"
        assert alert["rule"]["description"] == "A rule for the tests"
        assert alert["threat"] == {
            "technique": {"id": ["T1059.001"]},
            "tactic": {"name": ["Execution"]},
        }
        assert alert["related"] == {"events": ["evt-1"]}
        assert alert["tartarus"]["analysis_id"] == 7
        assert alert["tartarus"]["detection"]["match"] == "process.command_line: run evil.exe"

    def test_the_rule_author_travels_with_the_alert(self, tmp_path: Path) -> None:
        rule = make_rule(tmp_path, author="Florian Roth")

        [outcome] = engine_for(rule).process(hit("evt-1", 0))

        assert isinstance(outcome, Emit)
        assert outcome.detection["rule"]["author"] == ["Florian Roth"]

    def test_a_rule_without_an_author_leaves_the_field_out(self, tmp_path: Path) -> None:
        [outcome] = engine_for(make_rule(tmp_path)).process(hit("evt-1", 0))

        assert isinstance(outcome, Emit)
        assert "author" not in outcome.detection["rule"]

    @pytest.mark.parametrize(
        ("level", "severity"),
        [("informational", 0), ("low", 1), ("medium", 2), ("high", 3), ("critical", 4), (None, 2)],
    )
    def test_the_level_becomes_the_event_severity(
        self, tmp_path: Path, level: str | None, severity: int
    ) -> None:
        [outcome] = engine_for(make_rule(tmp_path, level=level)).process(hit("e", 0))

        assert isinstance(outcome, Emit)
        assert outcome.detection["event"]["severity"] == severity

    def test_the_alert_takes_the_time_lane_and_process_of_the_triggering_event(
        self, tmp_path: Path
    ) -> None:
        trigger = hit("evt-1", 12.5, lane="file")

        [outcome] = engine_for(make_rule(tmp_path)).process(trigger)

        assert isinstance(outcome, Emit)
        alert = outcome.detection
        assert alert["@timestamp"] == at(12.5)
        assert alert["tartarus"]["lane"] == "file"
        assert alert["process"] == trigger["process"]

    def test_the_alert_does_not_share_its_process_with_the_event(self, tmp_path: Path) -> None:
        trigger = hit("evt-1", 0)
        pristine = copy.deepcopy(trigger)

        [outcome] = engine_for(make_rule(tmp_path)).process(trigger)

        assert isinstance(outcome, Emit)
        outcome.detection["process"]["name"] = "changed"
        assert trigger == pristine

    def test_a_missing_lane_falls_back_to_the_process_lane(self, tmp_path: Path) -> None:
        trigger = hit("evt-1", 0)
        del trigger["tartarus"]  # type: ignore[arg-type]

        [outcome] = engine_for(make_rule(tmp_path)).process(trigger)

        assert isinstance(outcome, Emit)
        assert outcome.detection["tartarus"]["lane"] == "process"

    def test_the_phase_is_recorded(self, tmp_path: Path) -> None:
        rule = make_rule(tmp_path)

        [live] = engine_for(rule, phase="live").process(hit("e", 0))
        [final] = engine_for(rule, phase="final").process(hit("e", 0))

        assert isinstance(live, Emit)
        assert isinstance(final, Emit)
        assert live.detection["tartarus"]["phase"] == "live"
        assert final.detection["tartarus"]["phase"] == "final"

    def test_the_id_depends_only_on_analysis_rule_and_triggering_event(
        self, tmp_path: Path
    ) -> None:
        rule = make_rule(tmp_path)
        other_rule = make_rule(tmp_path, rule_id=OTHER_ID, name="other.yml")

        def alert_id(engine: SigmaEngine, event: Event) -> str:
            [outcome] = engine.process(event)
            assert isinstance(outcome, Emit)
            return str(outcome.detection["event"]["id"])

        first = alert_id(engine_for(rule), hit("evt-1", 0))
        same_again = alert_id(engine_for(rule, phase="live"), hit("evt-1", 0))
        later_run = alert_id(engine_for(make_rule(tmp_path)), hit("evt-1", 500))

        assert first == same_again == later_run
        assert alert_id(engine_for(rule), hit("evt-2", 0)) != first
        assert alert_id(engine_for(other_rule), hit("evt-1", 0)) != first
        other_analysis = SigmaEngine([rule], IngestContext(8, CONTEXT.started_at))
        assert alert_id(other_analysis, hit("evt-1", 0)) != first

    def test_an_alert_is_not_matched_again(self, tmp_path: Path) -> None:
        engine = engine_for(make_rule(tmp_path, needle="Evil"))
        [outcome] = engine.process(hit("evt-1", 0))
        assert isinstance(outcome, Emit)

        assert engine.process(outcome.detection) == []

    @pytest.mark.parametrize("damage", ["no-timestamp", "bad-timestamp", "no-id"])
    def test_an_event_that_cannot_be_placed_or_identified_is_skipped(
        self, tmp_path: Path, damage: str
    ) -> None:
        trigger = hit("evt-1", 0)
        if damage == "no-timestamp":
            del trigger["@timestamp"]
        elif damage == "bad-timestamp":
            trigger["@timestamp"] = "yesterday"
        else:
            trigger["event"] = {"action": "process-created"}

        assert engine_for(make_rule(tmp_path)).process(trigger) == []

    def test_a_rule_that_raises_does_not_stop_the_others(self, tmp_path: Path) -> None:
        def explodes(_: Event) -> bool:
            raise RuntimeError

        good = make_rule(tmp_path)
        bad = fake_rule("bad", "process_creation", explodes)

        outcomes = engine_for(bad, good).process(hit("evt-1", 0))

        assert [type(o) for o in outcomes] == [Emit]


class TestSuppression:
    def run(self, tmp_path: Path, events: list[dict[str, object]]) -> list[Emit | Repeat]:
        return feed(engine_for(make_rule(tmp_path)), events)

    def test_a_repeat_in_the_window_only_counts(self, tmp_path: Path) -> None:
        first, second, third = self.run(tmp_path, [hit("a", 0), hit("b", 10), hit("c", 30)])

        assert isinstance(first, Emit)
        assert second == Repeat(first.detection["event"]["id"], 1)
        assert third == Repeat(first.detection["event"]["id"], 2)

    def test_the_window_is_measured_on_the_events_own_time(self, tmp_path: Path) -> None:
        outcomes = self.run(tmp_path, [hit("a", 0), hit("b", 59.999), hit("c", 60)])

        assert [type(o) for o in outcomes] == [Emit, Repeat, Emit]

    def test_the_window_opens_at_the_emitted_detection_and_does_not_slide(
        self, tmp_path: Path
    ) -> None:
        outcomes = self.run(tmp_path, [hit("a", 0), hit("b", 50), hit("c", 100), hit("d", 130)])

        assert [type(o) for o in outcomes] == [Emit, Repeat, Emit, Repeat]

    def test_wall_clock_plays_no_part(self, tmp_path: Path) -> None:
        # All four events are fed within microseconds of each other, hours apart in event time.
        outcomes = self.run(tmp_path, [hit("a", 0), hit("b", 3600), hit("c", 7200), hit("d", 7201)])

        assert [type(o) for o in outcomes] == [Emit, Emit, Emit, Repeat]

    def test_each_process_has_its_own_window(self, tmp_path: Path) -> None:
        events = [
            hit("a", 0, entity_id="7:1@x"),
            hit("b", 1, entity_id="7:2@x"),
            hit("c", 2, entity_id="7:1@x"),
        ]

        assert [type(o) for o in self.run(tmp_path, events)] == [Emit, Emit, Repeat]

    def test_events_without_a_process_entity_share_one_window_per_rule(
        self, tmp_path: Path
    ) -> None:
        events = [hit("a", 0, entity_id=None), hit("b", 1, entity_id=None)]

        assert [type(o) for o in self.run(tmp_path, events)] == [Emit, Repeat]

    def test_each_rule_has_its_own_window(self, tmp_path: Path) -> None:
        first = make_rule(tmp_path)
        second = make_rule(tmp_path, rule_id=OTHER_ID, name="second.yml")
        engine = engine_for(first, second)

        outcomes = engine.process(hit("a", 0)) + engine.process(hit("b", 1))

        assert [type(o) for o in outcomes] == [Emit, Emit, Repeat, Repeat]

    def test_the_first_trigger_stays_the_related_event(self, tmp_path: Path) -> None:
        first, _ = self.run(tmp_path, [hit("a", 0), hit("b", 1)])

        assert isinstance(first, Emit)
        assert first.detection["related"] == {"events": ["a"]}
        assert "repeated" not in first.detection["tartarus"]["detection"]

    def test_apply_repeats_writes_the_count_into_the_emitted_alert(self, tmp_path: Path) -> None:
        outcomes = self.run(tmp_path, [hit("a", 0), hit("b", 1), hit("c", 2), hit("d", 70)])

        alerts = apply_repeats(outcomes)

        assert [a["tartarus"]["detection"].get("repeated") for a in alerts] == [2, None]
        assert alerts[0]["related"] == {"events": ["a"]}


class TestDeterminism:
    @pytest.fixture
    def stream(self) -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        for number in range(40):
            entity = f"7:{number % 3}@x"
            line = "run evil.exe" if number % 2 == 0 else "run fine.exe"
            events.append(
                process_event(f"evt-{number}", at(number * 9), entity_id=entity, command_line=line)
            )
        return events

    def test_the_same_events_give_the_same_outcomes(
        self, tmp_path: Path, stream: list[dict[str, object]]
    ) -> None:
        rule = make_rule(tmp_path)

        first = feed(engine_for(rule), stream)
        again = feed(engine_for(rule), stream)

        assert first == again
        assert any(isinstance(o, Emit) for o in first)
        assert any(isinstance(o, Repeat) for o in first)

    def test_feeding_the_events_in_batches_changes_nothing(
        self, tmp_path: Path, stream: list[dict[str, object]]
    ) -> None:
        rule = make_rule(tmp_path)
        whole = feed(engine_for(rule), stream)

        for split in (1, 7, 20, 39):
            batched = engine_for(rule)
            first_batch = feed(batched, stream[:split])
            second_batch = feed(batched, stream[split:])
            assert first_batch + second_batch == whole
