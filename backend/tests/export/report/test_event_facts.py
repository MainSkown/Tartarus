from datetime import UTC, datetime
from typing import Any

from app.db.models.analysis import Severity
from app.events.event_model import event_from_source
from app.export.report.key_events import (
    facts_from_detection,
    facts_from_event,
    facts_from_related,
)
from app.schemas.views_events import ProcessRef
from app.schemas.views_findings import Detection, RelatedEvent

MOMENT = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)


def indexed(**sections: Any) -> dict[str, Any]:
    return {
        "@timestamp": "2026-10-01T12:00:00Z",
        "event": {"id": "ev1", "sequence": 7, "action": "dns-query", "severity": 3},
        "tartarus": {"lane": "network", "summary": "lookup"},
        "process": {"pid": 44, "name": "a.exe"},
        **sections,
    }


def test_an_indexed_event_keeps_what_the_report_shows() -> None:
    facts = facts_from_event(event_from_source(indexed()))

    assert (facts.id, facts.sequence, facts.lane, facts.action, facts.summary) == (
        "ev1",
        7,
        "network",
        "dns-query",
        "lookup",
    )
    assert (facts.severity, facts.process_name, facts.pid) == (Severity.HIGH, "a.exe", 44)


def test_an_event_missing_its_lane_and_summary_shows_them_empty() -> None:
    source = indexed(tartarus={})

    facts = facts_from_event(event_from_source(source))

    assert (facts.lane, facts.summary) == ("", "")


def test_the_destination_is_the_dns_name_before_the_domain_before_the_ip_before_the_url() -> None:
    by_dns = indexed(dns={"question": {"name": "q.example"}}, destination={"ip": "1.1.1.1"})
    by_domain = indexed(destination={"domain": "d.example", "ip": "1.1.1.1"})
    by_ip = indexed(destination={"ip": "1.1.1.1"}, url={"full": "http://u.example/"})
    by_url = indexed(url={"full": "http://u.example/"})

    destinations = [
        facts_from_event(event_from_source(source)).destination
        for source in (by_dns, by_domain, by_ip, by_url, indexed())
    ]

    assert destinations == ["q.example", "d.example", "1.1.1.1", "http://u.example/", None]


def test_a_detection_stands_for_its_alert_event_under_its_rule_name() -> None:
    detection = Detection(
        id="alert-1",
        name="Run key written",
        description="long text",
        severity=Severity.HIGH,
        ruleset="sigma",
        techniques=[],
        match=None,
        references=[],
        time=MOMENT,
        process=ProcessRef(pid=5, name="x.exe"),
        related_events=[],
        related_event_total=0,
    )

    facts = facts_from_detection(detection)

    assert (facts.id, facts.time, facts.lane, facts.summary) == (
        "alert-1",
        MOMENT,
        "alert",
        "Run key written",
    )
    assert (facts.severity, facts.process_name, facts.pid) == (Severity.HIGH, "x.exe", 5)


def test_a_related_event_of_a_detection_has_no_severity() -> None:
    related = RelatedEvent(
        id="r1",
        time=MOMENT,
        lane="api",
        action="NtCreateFile",
        summary="created",
        process=None,
    )

    facts = facts_from_related(related)

    assert (facts.id, facts.lane, facts.action, facts.severity, facts.pid) == (
        "r1",
        "api",
        "NtCreateFile",
        None,
        None,
    )
