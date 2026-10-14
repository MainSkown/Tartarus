from collections.abc import Callable, Iterable, Sequence
from typing import Any

from app.ingest.protocol import IngestContext
from app.rules.categories import category_of
from app.rules.detections import event_time
from app.rules.engine import SigmaEngine, apply_repeats
from app.rules.rule import Rule

Event = dict[str, Any]

type RulesProvider = Callable[[], Sequence[Rule]]


def no_rules() -> Sequence[Rule]:
    return ()


def can_match_a_rule(event: Event) -> bool:
    """Whether some Sigma logsource category covers the event, so the engine has a use for it."""
    section = event.get("event")
    return isinstance(section, dict) and category_of(section.get("action")) is not None


def in_event_time_order(events: Iterable[Event]) -> list[Event]:
    """Events by `@timestamp`, ties in the order given; events with no usable time are left out.

    The engine needs time order, and skips an event without a time anyway.
    """
    timed = [(moment, event) for event in events if (moment := event_time(event)) is not None]
    timed.sort(key=lambda pair: pair[0])
    return [event for _, event in timed]


def final_detections(
    rules: Sequence[Rule], context: IngestContext, events: Iterable[Event]
) -> list[Event]:
    """The Sigma alerts of a complete event set, each with its final repeat count."""
    engine = SigmaEngine(rules, context, phase="final")
    return apply_repeats(
        outcome for event in in_event_time_order(events) for outcome in engine.process(event)
    )
