import asyncio
from datetime import UTC, datetime
from typing import Any

import pytest

from app.live.hub import LiveFilter, LiveHub, Subscription
from app.live.messages import (
    CountsMessage,
    ErrorMessage,
    EventsMessage,
    LiveMessage,
    ProcessMessage,
)
from tests.live.events import make_event

ANALYSIS = 7
OTHER_ANALYSIS = 8
BATCH_S = 0.25
COUNTS_S = 2.0
BOUND = 5


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def hub(clock: Clock) -> LiveHub:
    return LiveHub(
        clock=clock,
        wall_clock=lambda: datetime(2026, 10, 13, tzinfo=UTC),
        queue_bound=BOUND,
        batch_interval_s=BATCH_S,
        counts_interval_s=COUNTS_S,
    )


def types(messages: list[LiveMessage]) -> list[str]:
    return [message.type for message in messages]


def delivered(messages: list[LiveMessage]) -> list[dict[str, Any]]:
    return [event for m in messages if isinstance(m, EventsMessage) for event in m.data.events]


def subscribe(
    hub: LiveHub, clock: Clock, filters: LiveFilter | None = None, analysis: int = ANALYSIS
) -> Subscription:
    subscription = hub.subscribe(analysis, filters or LiveFilter())
    subscription.poll(clock.now)  # the snapshot every subscriber starts with
    return subscription


def ids(events: list[dict[str, Any]]) -> list[str]:
    return [event["event"]["id"] for event in events]


def test_a_new_subscriber_starts_with_the_process_tree_then_the_counts(
    hub: LiveHub, clock: Clock
) -> None:
    hub.publish(
        ANALYSIS,
        [make_event("file", pid=10, severity=2), make_event("api", pid=20, severity=0)],
    )

    messages = hub.subscribe(ANALYSIS, LiveFilter()).poll(clock.now)

    assert types(messages) == ["process", "process", "counts"]
    added = [m.data for m in messages if isinstance(m, ProcessMessage)]
    assert [(d.op, d.node.pid) for d in added] == [("add", 10), ("add", 20)]
    counts = messages[-1]
    assert isinstance(counts, CountsMessage)
    assert counts.data.total == 2
    assert counts.data.by_lane == {"file": 1, "api": 1}
    assert counts.data.by_severity == {"medium": 1, "info": 1}


def test_a_subscriber_never_sees_events_published_before_it_subscribed(
    hub: LiveHub, clock: Clock
) -> None:
    hub.publish(ANALYSIS, [make_event("file")])

    subscription = hub.subscribe(ANALYSIS, LiveFilter())
    clock.now += 10

    assert delivered(subscription.poll(clock.now)) == []


def test_events_are_delivered_without_tartarus_raw_and_the_original_keeps_it(
    hub: LiveHub, clock: Clock
) -> None:
    subscription = subscribe(hub, clock)
    event = make_event("file")

    hub.publish(ANALYSIS, [event])
    [received] = delivered(subscription.poll(clock.now))

    assert "raw" not in received["tartarus"]
    assert received["event"]["id"] == event["event"]["id"]
    assert event["tartarus"]["raw"] == {"api": "NtSomething"}


def test_the_api_lane_is_left_out_unless_asked_for(hub: LiveHub, clock: Clock) -> None:
    quiet = subscribe(hub, clock)
    noisy = subscribe(hub, clock, LiveFilter(include_api=True))
    file_event, api_event = make_event("file"), make_event("api")

    hub.publish(ANALYSIS, [file_event, api_event])

    assert ids(delivered(quiet.poll(clock.now))) == [file_event["event"]["id"]]
    assert ids(delivered(noisy.poll(clock.now))) == [
        file_event["event"]["id"],
        api_event["event"]["id"],
    ]


def test_naming_the_api_lane_is_asking_for_it(hub: LiveHub, clock: Clock) -> None:
    subscription = subscribe(hub, clock, LiveFilter(lanes=frozenset({"api"})))
    api_event = make_event("api")

    hub.publish(ANALYSIS, [make_event("file"), api_event])

    assert ids(delivered(subscription.poll(clock.now))) == [api_event["event"]["id"]]


def test_lanes_and_pids_narrow_what_a_subscriber_receives(hub: LiveHub, clock: Clock) -> None:
    subscription = subscribe(
        hub, clock, LiveFilter(lanes=frozenset({"file", "network"}), pids=frozenset({10}))
    )
    wanted = make_event("network", pid=10)

    hub.publish(
        ANALYSIS,
        [make_event("file", pid=11), make_event("registry", pid=10), wanted],
    )

    assert ids(delivered(subscription.poll(clock.now))) == [wanted["event"]["id"]]


def test_subscribers_with_different_filters_get_different_events(
    hub: LiveHub, clock: Clock
) -> None:
    files = subscribe(hub, clock, LiveFilter(lanes=frozenset({"file"})))
    registry = subscribe(hub, clock, LiveFilter(lanes=frozenset({"registry"})))
    file_event, registry_event = make_event("file"), make_event("registry")

    hub.publish(ANALYSIS, [file_event, registry_event])

    assert ids(delivered(files.poll(clock.now))) == [file_event["event"]["id"]]
    assert ids(delivered(registry.poll(clock.now))) == [registry_event["event"]["id"]]


def test_counts_include_the_events_a_subscriber_filtered_out(hub: LiveHub, clock: Clock) -> None:
    subscription = subscribe(hub, clock, LiveFilter(lanes=frozenset({"file"})))

    hub.publish(ANALYSIS, [make_event("file"), make_event("api"), make_event("api", severity=4)])
    clock.now += COUNTS_S
    [counts] = [m for m in subscription.poll(clock.now) if isinstance(m, CountsMessage)]

    assert counts.data.total == 3
    assert counts.data.by_lane == {"file": 1, "api": 2}
    assert counts.data.by_severity == {"info": 2, "critical": 1}


def test_a_full_queue_keeps_the_newest_events_and_reports_exactly_how_many_it_dropped(
    hub: LiveHub, clock: Clock
) -> None:
    subscription = subscribe(hub, clock)
    events = [make_event("file") for _ in range(BOUND + 3)]

    hub.publish(ANALYSIS, events)
    [message] = [m for m in subscription.poll(clock.now) if isinstance(m, EventsMessage)]

    assert ids(message.data.events) == ids(events[3:])
    assert message.data.dropped == 3


def test_dropped_is_reported_once_and_then_starts_again_from_zero(
    hub: LiveHub, clock: Clock
) -> None:
    subscription = subscribe(hub, clock)
    hub.publish(ANALYSIS, [make_event("file") for _ in range(BOUND + 2)])
    subscription.poll(clock.now)
    clock.now += BATCH_S

    hub.publish(ANALYSIS, [make_event("file")])
    [message] = [m for m in subscription.poll(clock.now) if isinstance(m, EventsMessage)]

    assert message.data.dropped == 0
    assert len(message.data.events) == 1


def test_events_filtered_out_are_not_counted_as_dropped(hub: LiveHub, clock: Clock) -> None:
    subscription = subscribe(hub, clock)

    hub.publish(ANALYSIS, [make_event("api") for _ in range(BOUND * 3)] + [make_event("file")])
    [message] = [m for m in subscription.poll(clock.now) if isinstance(m, EventsMessage)]

    assert (len(message.data.events), message.data.dropped) == (1, 0)


def test_a_subscriber_gets_at_most_one_events_message_per_batch_interval(
    hub: LiveHub, clock: Clock
) -> None:
    subscription = subscribe(hub, clock)
    first, second, third = make_event("file"), make_event("file"), make_event("file")

    hub.publish(ANALYSIS, [first])
    sent_first = subscription.poll(clock.now)
    clock.now += BATCH_S / 2
    hub.publish(ANALYSIS, [second])
    hub.publish(ANALYSIS, [third])
    too_soon = subscription.poll(clock.now)
    clock.now += BATCH_S / 2
    sent_later = subscription.poll(clock.now)

    assert ids(delivered(sent_first)) == ids([first])
    assert delivered(too_soon) == []
    assert types(sent_later) == ["events"]
    assert ids(delivered(sent_later)) == ids([second, third])


def test_the_wait_until_the_next_batch_is_the_rest_of_the_interval(
    hub: LiveHub, clock: Clock
) -> None:
    subscription = subscribe(hub, clock)
    hub.publish(ANALYSIS, [make_event("file")])
    subscription.poll(clock.now)
    clock.now += 0.1
    hub.publish(ANALYSIS, [make_event("file")])

    assert subscription.seconds_until_due(clock.now) == pytest.approx(BATCH_S - 0.1)


def test_process_changes_are_sent_at_once_ahead_of_the_events_they_belong_to(
    hub: LiveHub, clock: Clock
) -> None:
    subscription = subscribe(hub, clock)
    hub.publish(ANALYSIS, [make_event("file", pid=1)])
    subscription.poll(clock.now)
    clock.now += 0.01

    hub.publish(ANALYSIS, [make_event("process", pid=2, action="process-created")])
    messages = subscription.poll(clock.now)

    assert types(messages) == ["process"]
    clock.now += BATCH_S
    assert types(subscription.poll(clock.now)) == ["events"]


def test_a_process_ending_is_announced_as_an_end(hub: LiveHub, clock: Clock) -> None:
    subscription = subscribe(hub, clock)

    hub.publish(
        ANALYSIS,
        [make_event("file", pid=2), make_event("process", pid=2, action="process-terminated")],
    )
    processes = [m for m in subscription.poll(clock.now) if isinstance(m, ProcessMessage)]

    assert [(m.data.op, m.data.node.pid) for m in processes] == [("add", 2), ("end", 2)]


def test_counts_arrive_every_two_seconds_while_subscribed(hub: LiveHub, clock: Clock) -> None:
    subscription = subscribe(hub, clock)

    clock.now += COUNTS_S - 0.1
    early = subscription.poll(clock.now)
    clock.now += 0.1
    on_time = subscription.poll(clock.now)
    clock.now += COUNTS_S - 0.1
    again_too_early = subscription.poll(clock.now)

    assert (types(early), types(on_time), types(again_too_early)) == ([], ["counts"], [])


def test_changing_the_filter_replaces_it_and_drops_queued_events_it_no_longer_lets_in(
    hub: LiveHub, clock: Clock
) -> None:
    subscription = subscribe(hub, clock)
    file_event, registry_event = make_event("file"), make_event("registry")
    hub.publish(ANALYSIS, [file_event, registry_event])

    subscription.set_filters(LiveFilter(lanes=frozenset({"registry"})))

    assert ids(delivered(subscription.poll(clock.now))) == [registry_event["event"]["id"]]
    hub.publish(ANALYSIS, [make_event("file")])
    clock.now += BATCH_S
    assert delivered(subscription.poll(clock.now)) == []


def test_an_error_reaches_every_subscriber_of_the_analysis_at_once(
    hub: LiveHub, clock: Clock
) -> None:
    mine, theirs = subscribe(hub, clock), subscribe(hub, clock, analysis=OTHER_ANALYSIS)

    hub.report_error(ANALYSIS, "log_format", "2476.bson is not a log")

    [error] = mine.poll(clock.now)
    assert isinstance(error, ErrorMessage)
    assert (error.data.code, error.data.message) == ("log_format", "2476.bson is not a log")
    assert theirs.poll(clock.now) == []


def test_analyses_do_not_see_each_others_events_or_counts(hub: LiveHub, clock: Clock) -> None:
    other = subscribe(hub, clock, analysis=OTHER_ANALYSIS)

    hub.publish(ANALYSIS, [make_event("file")])
    clock.now += COUNTS_S
    messages = other.poll(clock.now)

    assert delivered(messages) == []
    [counts] = [m for m in messages if isinstance(m, CountsMessage)]
    assert counts.data.total == 0


def test_the_state_of_an_analysis_lives_while_it_is_collected_or_watched(hub: LiveHub) -> None:
    hub.open(ANALYSIS)
    hub.publish(ANALYSIS, [make_event("file")])
    watcher = hub.subscribe(ANALYSIS, LiveFilter())

    hub.close(ANALYSIS)
    assert hub.is_tracking(ANALYSIS)
    watcher.close()

    assert not hub.is_tracking(ANALYSIS)


def test_closing_an_analysis_nobody_watches_drops_its_state_at_once(hub: LiveHub) -> None:
    hub.open(ANALYSIS)
    hub.publish(ANALYSIS, [make_event("file")])

    hub.close(ANALYSIS)

    assert not hub.is_tracking(ANALYSIS)
    [counts] = [m for m in hub.subscribe(ANALYSIS, LiveFilter()).poll(0.0) if m.type == "counts"]
    assert isinstance(counts, CountsMessage)
    assert counts.data.total == 0


def test_a_subscriber_that_is_watching_a_collected_analysis_leaves_its_state_alone(
    hub: LiveHub,
) -> None:
    hub.open(ANALYSIS)

    hub.subscribe(ANALYSIS, LiveFilter()).close()

    assert hub.is_tracking(ANALYSIS)


async def test_waiting_for_messages_ends_as_soon_as_events_are_published() -> None:
    hub = LiveHub(batch_interval_s=0.0)
    subscription = hub.subscribe(ANALYSIS, LiveFilter())
    subscription.poll(0.0)
    waiter = asyncio.create_task(subscription.next_messages(timeout_s=5.0))
    await asyncio.sleep(0)

    hub.publish(ANALYSIS, [make_event("file")])
    messages = await asyncio.wait_for(waiter, 1.0)

    assert types(messages) == ["process", "events"]


async def test_waiting_for_messages_gives_up_at_the_timeout_with_nothing() -> None:
    hub = LiveHub()
    subscription = hub.subscribe(ANALYSIS, LiveFilter())
    subscription.poll(0.0)

    assert await subscription.next_messages(timeout_s=0.01) == []


def test_flushing_hands_over_everything_queued_regardless_of_the_batch_interval(
    hub: LiveHub, clock: Clock
) -> None:
    subscription = subscribe(hub, clock)
    hub.publish(ANALYSIS, [make_event("file", pid=3)])
    subscription.poll(clock.now)
    clock.now += 0.01
    waiting = make_event("file", pid=4)
    hub.publish(ANALYSIS, [waiting])

    flushed = subscription.flush()

    assert types(flushed) == ["process", "events"]
    assert ids(delivered(flushed)) == [waiting["event"]["id"]]
    assert subscription.flush() == []
