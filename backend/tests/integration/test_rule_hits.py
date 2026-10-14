from collections.abc import AsyncIterator
from typing import Any

import pytest
from opensearchpy import AsyncOpenSearch

from app.search.client import create_opensearch_client
from app.search.index import EventIndex
from app.views.rule_hits import hits_across_analyses, hits_in_analysis

pytestmark = pytest.mark.integration

FIRST_ANALYSIS = 4301
SECOND_ANALYSIS = 4302
UNTOUCHED_ANALYSIS = 4303
RULE_A = "0a0a0a0a-0a0a-4a0a-8a0a-0a0a0a0a0a0a"
RULE_B = "0b0b0b0b-0b0b-4b0b-8b0b-0b0b0b0b0b0b"
CAPE_RULE = "0c0c0c0c-0c0c-4c0c-8c0c-0c0c0c0c0c0c"


def document(number: int, kind: str, ruleset: str | None = None, rule_id: str | None = None) -> Any:
    event: dict[str, Any] = {"event": {"id": f"hit-{number}", "sequence": number, "kind": kind}}
    if rule_id is not None:
        event["rule"] = {"id": rule_id, "ruleset": ruleset}
    return event


@pytest.fixture
async def client(opensearch_url: str) -> AsyncIterator[AsyncOpenSearch]:
    opensearch = create_opensearch_client(opensearch_url)
    yield opensearch
    await opensearch.close()


@pytest.fixture
async def index(client: AsyncOpenSearch) -> AsyncIterator[EventIndex]:
    events_index = EventIndex(client)
    await events_index.ensure_template()
    for analysis_id in (FIRST_ANALYSIS, SECOND_ANALYSIS, UNTOUCHED_ANALYSIS):
        await events_index.drop(analysis_id)
        await events_index.create(analysis_id)
    await events_index.bulk_index(
        FIRST_ANALYSIS,
        [
            document(1, "alert", "sigma", RULE_A),
            document(2, "alert", "sigma", RULE_A),
            document(3, "alert", "sigma", RULE_B),
            document(4, "alert", "cape", CAPE_RULE),
            document(5, "event"),
            # Only an alert is a hit, whatever else carries a rule id.
            document(6, "event", "sigma", RULE_A),
        ],
    )
    await events_index.bulk_index(SECOND_ANALYSIS, [document(1, "alert", "sigma", RULE_A)])
    for analysis_id in (FIRST_ANALYSIS, SECOND_ANALYSIS, UNTOUCHED_ANALYSIS):
        await events_index.refresh(analysis_id)
    yield events_index
    for analysis_id in (FIRST_ANALYSIS, SECOND_ANALYSIS, UNTOUCHED_ANALYSIS):
        await events_index.drop(analysis_id)


async def test_a_rule_counts_its_sigma_alerts_in_one_analysis(index: EventIndex) -> None:
    hits = await hits_in_analysis(index, FIRST_ANALYSIS)

    assert hits == {RULE_A: 2, RULE_B: 1}


async def test_an_analysis_with_no_alerts_has_no_hits(index: EventIndex) -> None:
    assert await hits_in_analysis(index, UNTOUCHED_ANALYSIS) == {}


async def test_an_analysis_with_no_index_has_no_hits(index: EventIndex) -> None:
    assert await hits_in_analysis(index, 999_999) == {}


async def test_the_total_adds_the_hits_of_every_analysis(index: EventIndex) -> None:
    hits = await hits_across_analyses(index)

    assert hits[RULE_A] == 3
    assert hits[RULE_B] == 1
    assert CAPE_RULE not in hits
