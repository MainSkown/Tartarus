import asyncio
import contextlib
import time
from collections import Counter, deque
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Self

from app.analyses.summary import SEVERITY_ORDER
from app.live.messages import (
    CountsData,
    CountsMessage,
    ErrorData,
    ErrorMessage,
    EventsData,
    EventsMessage,
    LiveMessage,
    ProcessData,
    ProcessMessage,
    SubscribeData,
)
from app.live.process_tree import ProcessTree

Event = dict[str, Any]

API_LANE = "api"
DEFAULT_QUEUE_BOUND = 1000
DEFAULT_BATCH_INTERVAL_S = 0.25
DEFAULT_COUNTS_INTERVAL_S = 2.0


@dataclass(frozen=True)
class LiveFilter:
    """What one subscriber wants. The noisy api lane is only delivered when asked for, either
    with `include_api` or by naming it in `lanes`."""

    lanes: frozenset[str] | None = None
    pids: frozenset[int] | None = None
    include_api: bool = False

    @classmethod
    def from_subscribe(cls, data: SubscribeData) -> Self:
        return cls(
            lanes=None if data.lanes is None else frozenset(data.lanes),
            pids=None if data.pids is None else frozenset(data.pids),
            include_api=data.include_api,
        )

    def matches(self, event: Event) -> bool:
        lane = event.get("tartarus", {}).get("lane")
        if (
            lane == API_LANE
            and not self.include_api
            and not (self.lanes and API_LANE in self.lanes)
        ):
            return False
        if self.lanes is not None and lane not in self.lanes:
            return False
        return self.pids is None or event.get("process", {}).get("pid") in self.pids


class Subscription:
    """One client's view of an analysis: a bounded queue of events plus immediate messages.

    The owner pulls with `next_messages`, or with `poll` where it controls the clock itself.
    When the queue is full the oldest events go, and the next `events` message says how many.
    """

    def __init__(  # noqa: PLR0913 - the hub's tuning handed to each subscription
        self,
        *,
        filters: LiveFilter,
        queue_bound: int,
        batch_interval_s: float,
        counts_interval_s: float,
        clock: Callable[[], float],
        wall_clock: Callable[[], datetime],
        counts: Callable[[], CountsData],
        on_close: Callable[["Subscription"], None],
    ) -> None:
        self._filters = filters
        self._queue_bound = queue_bound
        self._batch_interval_s = batch_interval_s
        self._counts_interval_s = counts_interval_s
        self._clock = clock
        self._wall_clock = wall_clock
        self._counts = counts
        self._on_close = on_close
        self._pending: deque[Event] = deque()
        self._dropped = 0
        self._immediate: deque[LiveMessage] = deque()
        self._last_events_at: float | None = None
        self._last_counts_at = clock()
        self._wake = asyncio.Event()
        self._closed = False

    def set_filters(self, filters: LiveFilter) -> None:
        self._filters = filters
        self._pending = deque(event for event in self._pending if filters.matches(event))

    def push(self, message: LiveMessage) -> None:
        self._immediate.append(message)
        self._wake.set()

    def push_error(self, code: str, message: str) -> None:
        self.push(ErrorMessage(ts=self._wall_clock(), data=ErrorData(code=code, message=message)))

    def push_process(self, delta: ProcessData) -> None:
        self.push(ProcessMessage(ts=self._wall_clock(), data=delta))

    def deliver(self, events: Iterable[Event]) -> None:
        for event in events:
            if not self._filters.matches(event):
                continue
            if len(self._pending) >= self._queue_bound:
                self._pending.popleft()
                self._dropped += 1
            self._pending.append(event)
        if self._pending:
            self._wake.set()

    def poll(self, now: float) -> list[LiveMessage]:
        messages = list(self._immediate)
        self._immediate.clear()
        if self._pending and self._batch_is_due(now):
            messages.append(self._take_batch(now))
        if now - self._last_counts_at >= self._counts_interval_s:
            self._last_counts_at = now
            messages.append(CountsMessage(ts=self._wall_clock(), data=self._counts()))
        return messages

    def flush(self) -> list[LiveMessage]:
        """Everything queued, now: for a connection that is about to end."""
        messages = list(self._immediate)
        self._immediate.clear()
        if self._pending:
            messages.append(self._take_batch(self._clock()))
        return messages

    def seconds_until_due(self, now: float) -> float:
        waits = [self._last_counts_at + self._counts_interval_s - now]
        if self._immediate:
            waits.append(0.0)
        if self._pending:
            waits.append(self._next_batch_at() - now)
        return max(0.0, min(waits))

    async def next_messages(self, timeout_s: float) -> list[LiveMessage]:
        """Waits for something to send; `[]` when nothing became due within `timeout_s`."""
        deadline = self._clock() + timeout_s
        while True:
            self._wake.clear()
            now = self._clock()
            if messages := self.poll(now):
                return messages
            patience = min(self.seconds_until_due(now), deadline - now)
            if patience <= 0:
                return []
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._wake.wait(), patience)

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            self._on_close(self)

    def _batch_is_due(self, now: float) -> bool:
        return now >= self._next_batch_at()

    def _next_batch_at(self) -> float:
        if self._last_events_at is None:
            return float("-inf")
        return self._last_events_at + self._batch_interval_s

    def _take_batch(self, now: float) -> EventsMessage:
        events, dropped = list(self._pending), self._dropped
        self._pending.clear()
        self._dropped = 0
        self._last_events_at = now
        return EventsMessage(ts=self._wall_clock(), data=EventsData(events=events, dropped=dropped))


@dataclass
class _AnalysisState:
    tree: ProcessTree = field(default_factory=ProcessTree)
    by_lane: Counter[str] = field(default_factory=Counter)
    by_severity: Counter[str] = field(default_factory=Counter)
    total: int = 0
    subscriptions: list[Subscription] = field(default_factory=list)
    collecting: bool = False

    def count(self, event: Event) -> None:
        self.total += 1
        self.by_lane[str(event.get("tartarus", {}).get("lane", "unknown"))] += 1
        self.by_severity[_severity_name(event)] += 1

    def counts(self) -> CountsData:
        return CountsData(
            by_lane=dict(self.by_lane), by_severity=dict(self.by_severity), total=self.total
        )


class LiveHub:
    """Fans the events of running analyses out to the WebSocket clients watching them.

    In process and single threaded: every method is synchronous and runs on the event loop. It
    keeps what a client that connects late needs: the process tree and the counts. That state
    lives while an analysis is being collected (`open` to `close`) or someone is subscribed.
    """

    def __init__(
        self,
        *,
        clock: Callable[[], float] = time.monotonic,
        wall_clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        queue_bound: int = DEFAULT_QUEUE_BOUND,
        batch_interval_s: float = DEFAULT_BATCH_INTERVAL_S,
        counts_interval_s: float = DEFAULT_COUNTS_INTERVAL_S,
    ) -> None:
        self._clock = clock
        self._wall_clock = wall_clock
        self._queue_bound = queue_bound
        self._batch_interval_s = batch_interval_s
        self._counts_interval_s = counts_interval_s
        self._states: dict[int, _AnalysisState] = {}

    def is_tracking(self, analysis_id: int) -> bool:
        return analysis_id in self._states

    def open(self, analysis_id: int) -> None:
        self._state(analysis_id).collecting = True

    def close(self, analysis_id: int) -> None:
        if (state := self._states.get(analysis_id)) is not None:
            state.collecting = False
            self._forget_if_idle(analysis_id)

    def subscribe(self, analysis_id: int, filters: LiveFilter) -> Subscription:
        state = self._state(analysis_id)
        subscription = Subscription(
            filters=filters,
            queue_bound=self._queue_bound,
            batch_interval_s=self._batch_interval_s,
            counts_interval_s=self._counts_interval_s,
            clock=self._clock,
            wall_clock=self._wall_clock,
            counts=state.counts,
            on_close=lambda closed: self._unsubscribe(analysis_id, closed),
        )
        for node in state.tree.snapshot():
            subscription.push_process(ProcessData(op="add", node=node))
        subscription.push(CountsMessage(ts=self._wall_clock(), data=state.counts()))
        state.subscriptions.append(subscription)
        return subscription

    def publish(self, analysis_id: int, events: list[Event]) -> None:
        state = self._state(analysis_id)
        for event in events:
            state.count(event)
            for delta in state.tree.observe(event):
                for subscription in state.subscriptions:
                    subscription.push_process(delta)
        if not state.subscriptions:
            return
        trimmed = [_without_raw(event) for event in events]
        for subscription in state.subscriptions:
            subscription.deliver(trimmed)

    def report_error(self, analysis_id: int, code: str, message: str) -> None:
        if (state := self._states.get(analysis_id)) is not None:
            for subscription in state.subscriptions:
                subscription.push_error(code, message)

    def _state(self, analysis_id: int) -> _AnalysisState:
        return self._states.setdefault(analysis_id, _AnalysisState())

    def _unsubscribe(self, analysis_id: int, subscription: Subscription) -> None:
        if (state := self._states.get(analysis_id)) is not None:
            if subscription in state.subscriptions:
                state.subscriptions.remove(subscription)
            self._forget_if_idle(analysis_id)

    def _forget_if_idle(self, analysis_id: int) -> None:
        state = self._states[analysis_id]
        if not state.collecting and not state.subscriptions:
            del self._states[analysis_id]


def _without_raw(event: Event) -> Event:
    tartarus = {key: value for key, value in event.get("tartarus", {}).items() if key != "raw"}
    return {**event, "tartarus": tartarus}


def _severity_name(event: Event) -> str:
    level = event.get("event", {}).get("severity", 0)
    if not isinstance(level, int) or not 0 <= level < len(SEVERITY_ORDER):
        return str(SEVERITY_ORDER[0])
    return str(SEVERITY_ORDER[level])
