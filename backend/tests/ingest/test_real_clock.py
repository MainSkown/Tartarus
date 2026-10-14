"""Eight real analyses: capemon and the pcap see the same lookup at the same moment.

Each `task_<N>.report.json` keeps only the clocks of a real CAPE report (process start times, the
sample's `getaddrinfo` call, `network.dns`) beside that task's real `cuckoo.log`.
"""

import json
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest

from app.ingest.cape_network import CapeNetworkNormalizer
from app.ingest.capemon import CapemonNormalizer
from app.ingest.clock import analysis_started, host_registrations
from app.ingest.protocol import IngestContext
from tests.ingest.test_report_clock import moment, selftest_lookups

CLOCK_FIXTURES = Path(__file__).parent.parent / "fixtures" / "cape" / "clock"
TASKS = (1, 2, 3, 4, 5, 6, 45, 133)
EXACT_TOLERANCE = timedelta(seconds=1)
OLD_GAP_RANGE = (timedelta(seconds=4), timedelta(seconds=8))


def real_context(task: int, *, with_log: bool = True) -> tuple[dict[str, Any], IngestContext]:
    report: dict[str, Any] = json.loads((CLOCK_FIXTURES / f"task_{task}.report.json").read_text())
    registrations = (
        host_registrations((CLOCK_FIXTURES / f"task_{task}.cuckoo.log").read_text())
        if with_log
        else {}
    )
    started = analysis_started(report)
    assert started is not None
    return report, IngestContext(
        analysis_id=task, started_at=started, host_registrations=registrations
    )


def lookup_gap(task: int, *, with_log: bool) -> timedelta:
    report, context = real_context(task, with_log=with_log)
    [from_capemon] = selftest_lookups(list(CapemonNormalizer().normalise(report, context)))
    [from_pcap] = selftest_lookups(list(CapeNetworkNormalizer().normalise(report, context)))
    return abs(moment(from_capemon) - moment(from_pcap))


@pytest.mark.parametrize("task", TASKS)
def test_capemon_and_the_pcap_agree_within_a_second_on_the_samples_own_lookup(task: int) -> None:
    assert lookup_gap(task, with_log=True) < EXACT_TOLERANCE


@pytest.mark.parametrize("task", TASKS)
def test_without_the_log_the_two_clocks_were_seconds_apart(task: int) -> None:
    low, high = OLD_GAP_RANGE
    assert low < lookup_gap(task, with_log=False) < high


def test_the_log_moves_the_events_by_the_skew_and_nothing_else() -> None:
    report, with_log = real_context(45)
    _, without_log = real_context(45, with_log=False)
    anchored = list(CapemonNormalizer().normalise(report, with_log))
    rounded = list(CapemonNormalizer().normalise(report, without_log))
    assert [e["event"]["id"] for e in anchored] == [e["event"]["id"] for e in rounded]
    shifts = {moment(a) - moment(r) for a, r in zip(anchored, rounded, strict=True)}
    assert shifts == {timedelta(seconds=5, milliseconds=297)}


def test_the_registrations_of_the_real_logs_are_all_found() -> None:
    for task in TASKS:
        report, context = real_context(task)
        pids = {p["process_id"] for p in report["behavior"]["processes"]}
        assert pids == set(context.host_registrations), task
