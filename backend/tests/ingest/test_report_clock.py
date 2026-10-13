"""The three CAPE-report normalisers together: one report, one clock."""

import copy
from datetime import UTC, datetime, timedelta
from typing import Any

from app.ingest.cape_network import CapeNetworkNormalizer
from app.ingest.cape_signatures import CapeSignaturesNormalizer
from app.ingest.capemon import CapemonNormalizer
from app.ingest.protocol import IngestContext, Normalizer

Event = dict[str, Any]
SAME_ACTION_TOLERANCE = timedelta(seconds=10)
SELFTEST_NAME = "tartarus-selftest.example"


def run_all(report: dict[str, Any], context: IngestContext) -> dict[str, list[Event]]:
    normalizers: list[Normalizer] = [
        CapemonNormalizer(),
        CapeNetworkNormalizer(),
        CapeSignaturesNormalizer(),
    ]
    return {n.source: list(n.normalise(report, context)) for n in normalizers}


def moment(event: Event) -> datetime:
    return datetime.fromisoformat(event["@timestamp"])


def window(report: dict[str, Any]) -> tuple[datetime, datetime]:
    def utc(text: str) -> datetime:
        return datetime.strptime(text, "%Y-%m-%d %H:%M:%S").replace(tzinfo=UTC)

    return (
        utc(report["info"]["started"]) - timedelta(seconds=5),
        utc(report["info"]["ended"]) + timedelta(seconds=60),
    )


def selftest_lookups(events: list[Event]) -> list[Event]:
    return [
        e
        for e in events
        if e["event"]["action"] == "dns-query" and e["dns"]["question"]["name"] == SELFTEST_NAME
    ]


def test_events_of_all_three_normalisers_fall_inside_one_analysis_window(
    full_report: dict[str, Any], context: IngestContext
) -> None:
    start, end = window(full_report)
    by_source = run_all(full_report, context)
    assert all(by_source.values())
    for source, events in by_source.items():
        for event in events:
            assert start <= moment(event) <= end, (source, event["@timestamp"])


def test_the_same_dns_lookup_is_seen_by_capemon_and_the_pcap_within_seconds(
    full_report: dict[str, Any], context: IngestContext
) -> None:
    by_source = run_all(full_report, context)
    [from_capemon] = selftest_lookups(by_source["capemon"])
    [from_pcap] = selftest_lookups(by_source["cape-network"])
    assert abs(moment(from_capemon) - moment(from_pcap)) < SAME_ACTION_TOLERANCE


def test_without_the_calibration_the_two_clocks_would_disagree_by_hours(
    full_report: dict[str, Any], context: IngestContext
) -> None:
    uncalibrated = copy.deepcopy(full_report)
    del uncalibrated["info"]
    by_source = run_all(uncalibrated, context)
    [from_capemon] = selftest_lookups(by_source["capemon"])
    [from_pcap] = selftest_lookups(by_source["cape-network"])
    assert abs(moment(from_capemon) - moment(from_pcap)) > timedelta(hours=1, minutes=59)


def test_an_alert_lands_beside_the_capemon_call_it_names(
    full_report: dict[str, Any], context: IngestContext
) -> None:
    by_source = run_all(full_report, context)
    capemon = {e["event"]["id"]: e for e in by_source["capemon"]}
    for alert in by_source["cape-signatures"]:
        for linked in alert.get("related", {}).get("events", []):
            assert moment(alert) <= moment(capemon[linked])
            assert abs(moment(alert) - moment(capemon[linked])) < timedelta(seconds=2)


def test_no_two_events_of_the_three_sources_share_an_id(
    full_report: dict[str, Any], context: IngestContext
) -> None:
    by_source = run_all(full_report, context)
    all_ids = [e["event"]["id"] for events in by_source.values() for e in events]
    assert len(set(all_ids)) == len(all_ids)
