from typing import Any

import pytest

from app.db.models import Analysis
from app.guest.selftest_evidence import read_evidence
from app.guest.selftest_verdict import DnsLookup
from tests.guest.selftest_fakes import CannedIndex, aggregations


def analysis_with(summary: dict[str, Any] | None) -> Analysis:
    return Analysis(id=41, summary=summary)


async def test_the_counts_come_from_one_search_of_the_analysis_own_index() -> None:
    index = CannedIndex(aggregations(processes=3, files=4, registry=2, lookup=2, answered=1))

    evidence = await read_evidence(index, analysis_with({"process_count": 3}))

    assert (evidence.process_count, evidence.file_events, evidence.registry_events) == (3, 4, 2)
    assert evidence.dns is DnsLookup.ANSWERED
    assert evidence.report_present is True
    [(analysis_id, body)] = index.searched
    assert analysis_id == 41
    assert body["size"] == 0


@pytest.mark.parametrize(
    ("lookup", "answered", "expected"),
    [(0, 0, DnsLookup.ABSENT), (1, 0, DnsLookup.UNANSWERED), (2, 1, DnsLookup.ANSWERED)],
)
async def test_the_dns_lookup_is_absent_unanswered_or_answered(
    lookup: int, answered: int, expected: DnsLookup
) -> None:
    index = CannedIndex(aggregations(lookup=lookup, answered=answered))

    evidence = await read_evidence(index, analysis_with(None))

    assert evidence.dns is expected
    assert evidence.report_present is False


async def test_an_analysis_with_no_index_has_nothing() -> None:
    index = CannedIndex({"hits": {"total": {"value": 0}, "hits": []}, "aggregations": {}})

    evidence = await read_evidence(index, analysis_with(None))

    assert (evidence.process_count, evidence.file_events, evidence.registry_events) == (0, 0, 0)
    assert evidence.dns is DnsLookup.ABSENT
