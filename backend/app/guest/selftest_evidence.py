"""Reads, from an analysis' own data, what the self-test's signals are judged on."""

from collections.abc import Mapping
from typing import Any, Protocol

from app.db.models import Analysis
from app.guest.selftest_verdict import SELFTEST_LOOKUP_NAME, DnsLookup, Evidence

LANES_COUNTED = ("file", "registry")


class EventSearch(Protocol):
    async def search(self, analysis_id: int, body: dict[str, Any]) -> dict[str, Any]: ...


def _evidence_query() -> dict[str, Any]:
    lookups = {
        "bool": {
            "filter": [
                {"term": {"tartarus.lane": "network"}},
                {"term": {"dns.question.name": SELFTEST_LOOKUP_NAME}},
            ]
        }
    }
    return {
        "size": 0,
        "aggs": {
            # Distinct processes, as the Processes tab lists them: any event names its process.
            "processes": {"cardinality": {"field": "process.entity_id"}},
            "lanes": {"terms": {"field": "tartarus.lane", "size": len(LANES_COUNTED) + 4}},
            "lookup": {
                "filter": lookups,
                "aggs": {"answered": {"filter": {"exists": {"field": "dns.answers.data"}}}},
            },
        },
    }


async def read_evidence(index: EventSearch, analysis: Analysis) -> Evidence:
    response = await index.search(analysis.id, _evidence_query())
    aggregations: Mapping[str, Any] = response.get("aggregations", {})
    lane_counts = {
        bucket["key"]: int(bucket["doc_count"])
        for bucket in aggregations.get("lanes", {}).get("buckets", [])
    }
    return Evidence(
        process_count=int(aggregations.get("processes", {}).get("value", 0)),
        file_events=lane_counts.get("file", 0),
        registry_events=lane_counts.get("registry", 0),
        dns=_dns_lookup(aggregations.get("lookup", {})),
        report_present=analysis.summary is not None,
    )


def _dns_lookup(lookup: Mapping[str, Any]) -> DnsLookup:
    if not lookup.get("doc_count"):
        return DnsLookup.ABSENT
    answered = lookup.get("answered", {}).get("doc_count", 0)
    return DnsLookup.ANSWERED if answered else DnsLookup.UNANSWERED
