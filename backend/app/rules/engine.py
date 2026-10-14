import copy
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from app.ingest.ecs import Phase
from app.ingest.protocol import IngestContext
from app.rules.detections import DetectionBuilder, entity_id_of, event_id_of, event_time
from app.rules.matcher import RuleMatcher
from app.rules.predicate import Event
from app.rules.rule import Rule
from app.rules.suppression import Suppression

SUPPRESSION_WINDOW = timedelta(seconds=60)


@dataclass(frozen=True)
class Emit:
    """A new detection: an `event.kind: alert` document to index and publish."""

    detection: dict[str, Any]


@dataclass(frozen=True)
class Repeat:
    """The rule matched again for the same process inside the window of an emitted detection.

    `count` is the number of repeats so far, so a later `Repeat` for the same `detection_id`
    replaces an earlier one. Set it as `tartarus.detection.repeated` on the document with
    `event.id == detection_id`.
    """

    detection_id: str
    count: int


type Outcome = Emit | Repeat


class SigmaEngine:
    """Evaluates Sigma rules over the events of one analysis, in order, and emits detections.

    Public interface for the collector (live) and the ingester (final):

        engine = SigmaEngine(rules, context, phase="live")
        for event in ordered_events:
            for outcome in engine.process(event):
                ...  # Emit(detection): index it; Repeat(id, count): update that detection

    One engine per analysis and phase. Events must be fed in time order; the same ordered
    events always give the same outcomes, however they are split into calls, and detection ids
    depend only on (analysis, rule, triggering event), so re-ingesting is idempotent.

    A rule gives one detection per (rule, `process.entity_id`) per 60 seconds of event time; a
    match inside that window is a `Repeat`. Events with no process entity share one window per
    rule. An event with no parseable `@timestamp` or no `event.id` is skipped. Rules that raise
    are disabled (see `RuleMatcher`); `disabled_rule_ids` lists them.
    """

    def __init__(
        self,
        rules: Iterable[Rule],
        context: IngestContext,
        *,
        phase: Phase = "final",
        window: timedelta = SUPPRESSION_WINDOW,
    ) -> None:
        self._matcher = RuleMatcher(rules)
        self._builder = DetectionBuilder(context, phase)
        self._suppression = Suppression(window)

    @property
    def disabled_rule_ids(self) -> frozenset[str]:
        return self._matcher.disabled_rule_ids

    def process(self, event: Event) -> list[Outcome]:
        matched = self._matcher.match(event)
        if not matched:
            return []
        moment, trigger_id = event_time(event), event_id_of(event)
        if moment is None or trigger_id is None:
            return []
        entity = entity_id_of(event)
        outcomes: list[Outcome] = []
        for rule in matched:
            key = (rule.id, entity)
            if repeated := self._suppression.repeat(key, moment):
                outcomes.append(Repeat(*repeated))
                continue
            detection = self._builder.build(rule, event, trigger_id, moment)
            self._suppression.open(key, moment, detection["event"]["id"])
            outcomes.append(Emit(detection))
        return outcomes


def apply_repeats(outcomes: Iterable[Outcome]) -> list[dict[str, Any]]:
    """The emitted detections of `outcomes`, each with its final `tartarus.detection.repeated`.

    For the final ingest, which holds all outcomes before indexing; the originals are not changed.
    """
    outcomes = list(outcomes)
    counts = {o.detection_id: o.count for o in outcomes if isinstance(o, Repeat)}
    detections = []
    for outcome in outcomes:
        if not isinstance(outcome, Emit):
            continue
        detection = copy.deepcopy(outcome.detection)
        if count := counts.get(detection["event"]["id"]):
            detection["tartarus"].setdefault("detection", {})["repeated"] = count
        detections.append(detection)
    return detections
