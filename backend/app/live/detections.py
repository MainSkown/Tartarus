import copy
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from app.ingest.protocol import IngestContext
from app.ingest.sigma import in_event_time_order
from app.rules.engine import Emit, SigmaEngine
from app.rules.rule import Rule

Event = dict[str, Any]


@dataclass
class Detected:
    """What one batch produced: `alerts` are new and go to the hub and the index; `updates` are
    alerts of earlier batches whose repeat count went up, which only the index needs."""

    alerts: list[Event] = field(default_factory=list)
    updates: list[Event] = field(default_factory=list)


class LiveDetections:
    """The Sigma engine over the batches of one running analysis (phase `live`).

    The rules are fixed at construction: a rule switched on or off later applies from the next
    run. Each batch is matched in event-time order. Across batches events are not guaranteed to
    be in time order (a process log can be read late); the engine then takes the late event as
    it comes: inside an open window of its rule and process it is a repeat, whatever its age,
    and a later trigger can be picked where the final ingest would pick the earlier one. That
    is accepted: live alerts are provisional and the final ingest, which sorts, replaces them.

    Alerts are returned as copies, because the repeat counts of a retained alert change.
    """

    def __init__(self, rules: Sequence[Rule], context: IngestContext) -> None:
        self._engine = SigmaEngine(rules, context, phase="live") if rules else None
        self._alerts: dict[str, Event] = {}

    def process(self, events: list[Event]) -> Detected:
        if self._engine is None:
            return Detected()
        fresh: list[str] = []
        repeated: dict[str, None] = {}
        for event in in_event_time_order(events):
            for outcome in self._engine.process(event):
                if isinstance(outcome, Emit):
                    alert_id = outcome.detection["event"]["id"]
                    self._alerts[alert_id] = outcome.detection
                    fresh.append(alert_id)
                else:
                    alert = self._alerts[outcome.detection_id]
                    alert["tartarus"].setdefault("detection", {})["repeated"] = outcome.count
                    repeated[outcome.detection_id] = None
        return Detected(
            alerts=[copy.deepcopy(self._alerts[i]) for i in fresh],
            updates=[copy.deepcopy(self._alerts[i]) for i in repeated if i not in set(fresh)],
        )
