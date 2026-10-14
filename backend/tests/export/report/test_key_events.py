from datetime import UTC, datetime, timedelta

import pytest

from app.db.models.analysis import Severity
from app.export.report.key_events import (
    CITED_PER_DETECTION,
    MAX_KEY_EVENTS,
    Citation,
    EventFacts,
    KeyEventCandidates,
    KeyEventReason,
    select_key_events,
)

START = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)


def event(
    event_id: str,
    second: int,
    lane: str = "api",
    destination: str | None = None,
    sequence: int | None = None,
) -> EventFacts:
    return EventFacts(
        id=event_id,
        time=START + timedelta(seconds=second),
        sequence=sequence,
        lane=lane,
        action="act",
        summary=f"summary of {event_id}",
        severity=None,
        process_name="p.exe",
        pid=10,
        destination=destination,
    )


def ids(selected) -> list[str]:
    return [key_event.id for key_event in selected.events]


def reasons(selected) -> dict[str, KeyEventReason]:
    return {key_event.id: key_event.reason for key_event in selected.events}


def candidates(**rungs: object) -> KeyEventCandidates:
    return KeyEventCandidates(**rungs)  # type: ignore[arg-type]


def test_every_rung_contributes_and_the_result_is_in_time_order() -> None:
    selected = select_key_events(
        candidates(
            alerts=[event("alert", 50, "process")],
            process=[event("proc", 40, "process")],
            file_and_registry=[event("file", 30, "file"), event("reg", 20, "registry")],
            citations=[Citation("d1", [event("cited", 10)], total=1)],
            network=[event("net", 5, "network", destination="evil.example")],
        )
    )

    assert ids(selected) == ["net", "cited", "reg", "file", "proc", "alert"]
    assert reasons(selected) == {
        "alert": KeyEventReason.ALERT,
        "proc": KeyEventReason.PROCESS,
        "file": KeyEventReason.FILE_OR_REGISTRY,
        "reg": KeyEventReason.FILE_OR_REGISTRY,
        "cited": KeyEventReason.CITED,
        "net": KeyEventReason.NETWORK,
    }


def test_events_with_the_same_time_keep_the_order_of_their_sequence_numbers() -> None:
    selected = select_key_events(
        candidates(process=[event("later", 1, sequence=9), event("earlier", 1, sequence=2)])
    )

    assert ids(selected) == ["earlier", "later"]


def test_when_over_the_cap_the_earlier_rungs_win() -> None:
    selected = select_key_events(
        candidates(
            alerts=[event("alert", 90)],
            process=[event("proc", 80)],
            file_and_registry=[event("file", 70)],
            citations=[Citation("d1", [event("cited", 60)], total=1)],
            network=[event("net", 1, destination="a")],
        ),
        cap=3,
    )

    assert ids(selected) == ["file", "proc", "alert"]
    assert selected.cut == 2


def test_the_rung_that_only_partly_fits_gives_its_earliest_events() -> None:
    selected = select_key_events(
        candidates(
            alerts=[event("alert", 90)],
            process=[event("p3", 30), event("p1", 10), event("p2", 20)],
        ),
        cap=3,
    )

    assert ids(selected) == ["p1", "p2", "alert"]


def test_the_default_cap_is_two_hundred() -> None:
    assert MAX_KEY_EVENTS == 200
    selected = select_key_events(
        candidates(process=[event(f"e{n}", n) for n in range(MAX_KEY_EVENTS + 25)])
    )

    assert len(selected.events) == MAX_KEY_EVENTS
    assert selected.cut == 25


def test_an_event_in_two_rungs_appears_once_under_the_first() -> None:
    selected = select_key_events(
        candidates(
            alerts=[event("both", 1, "process")],
            process=[event("both", 1, "process")],
            citations=[Citation("d1", [event("both", 1, "process")], total=1)],
        )
    )

    assert ids(selected) == ["both"]
    assert reasons(selected) == {"both": KeyEventReason.ALERT}


def test_a_duplicate_does_not_use_up_a_place_under_the_cap() -> None:
    selected = select_key_events(
        candidates(
            alerts=[event("a", 1)],
            process=[event("a", 1), event("b", 2)],
        ),
        cap=2,
    )

    assert ids(selected) == ["a", "b"]
    assert selected.cut == 0


def test_a_detection_cites_at_most_five_events_the_earliest_ones() -> None:
    cited = [event(f"c{n}", n) for n in range(8, 0, -1)]
    selected = select_key_events(candidates(citations=[Citation("d1", cited, total=8)]))

    assert CITED_PER_DETECTION == 5
    assert ids(selected) == ["c1", "c2", "c3", "c4", "c5"]
    assert selected.more_cited == {"d1": 3}


def test_the_more_note_counts_what_the_detection_cites_beyond_the_events_it_lists() -> None:
    cited = [event(f"c{n}", n) for n in range(50)]
    selected = select_key_events(candidates(citations=[Citation("d1", cited, total=136)]))

    assert selected.more_cited == {"d1": 131}


def test_a_detection_with_five_or_fewer_citations_has_no_more_note() -> None:
    selected = select_key_events(
        candidates(
            citations=[
                Citation("d1", [event(f"c{n}", n) for n in range(5)], total=5),
                Citation("d2", [], total=0),
            ]
        )
    )

    assert selected.more_cited == {}


def test_each_detection_gets_its_own_five_and_cited_events_come_from_any_lane() -> None:
    first = [event(f"a{n}", n, "api") for n in range(6)]
    second = [event(f"b{n}", 100 + n, "file") for n in range(6)]
    selected = select_key_events(
        candidates(citations=[Citation("d1", first, total=6), Citation("d2", second, total=6)])
    )

    assert len(selected.events) == 10
    assert {key_event.lane for key_event in selected.events} == {"api", "file"}
    assert selected.more_cited == {"d1": 1, "d2": 1}


def test_an_event_cited_by_two_detections_appears_once() -> None:
    shared = event("shared", 1)
    selected = select_key_events(
        candidates(citations=[Citation("d1", [shared], total=1), Citation("d2", [shared], total=1)])
    )

    assert ids(selected) == ["shared"]


def test_only_the_first_network_event_of_each_destination_is_kept() -> None:
    selected = select_key_events(
        candidates(
            network=[
                event("n1", 1, "network", destination="a.example"),
                event("n2", 2, "network", destination="b.example"),
                event("n3", 3, "network", destination="a.example"),
                event("n4", 4, "network", destination="b.example"),
            ]
        )
    )

    assert ids(selected) == ["n1", "n2"]


def test_the_first_network_event_is_the_earliest_even_when_the_list_is_not_in_order() -> None:
    selected = select_key_events(
        candidates(
            network=[
                event("late", 9, "network", destination="a.example"),
                event("early", 1, "network", destination="a.example"),
            ]
        )
    )

    assert ids(selected) == ["early"]


def test_a_network_event_without_a_destination_is_left_out() -> None:
    selected = select_key_events(candidates(network=[event("n1", 1, "network")]))

    assert selected.events == ()


@pytest.mark.parametrize("severity", [Severity.HIGH, None])
def test_the_severity_of_an_event_is_carried(severity: Severity | None) -> None:
    alert = event("a", 1).model_copy(update={"severity": severity})

    selected = select_key_events(candidates(alerts=[alert]))

    assert selected.events[0].severity is severity


def test_nothing_in_gives_nothing_out() -> None:
    selected = select_key_events(candidates())

    assert (selected.events, selected.cut, selected.more_cited) == ((), 0, {})
