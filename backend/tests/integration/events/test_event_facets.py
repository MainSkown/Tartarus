from collections import Counter
from typing import Any

import pytest

from tests.integration.events.conftest import all_events, events_url, post_ok
from tests.integration.views.conftest import ViewStack
from tests.integration.views.helpers import add_analysis_without_index

pytestmark = pytest.mark.integration


def facet_of(response: dict[str, Any], field: str) -> dict[str, Any]:
    return next(facet for facet in response["facets"] if facet["field"] == field)


async def count_matching(stack: ViewStack, **filters: Any) -> int:
    page = await post_ok(stack, "search", {"size": 1, **filters})
    return int(page["total"])


async def test_without_fields_the_six_default_facets_are_returned(view_stack: ViewStack) -> None:
    response = await post_ok(view_stack, "facets", {})

    assert [facet["field"] for facet in response["facets"]] == [
        "process.name",
        "tartarus.lane",
        "event.action",
        "api.name",
        "destination.domain",
        "rule.name",
    ]


async def test_a_facet_counts_the_top_values_and_the_events_that_have_one(
    view_stack: ViewStack,
) -> None:
    events = await all_events(view_stack)

    response = await post_ok(view_stack, "facets", {"fields": ["api.name", "lane"]})

    api_names = Counter(event["api"]["name"].lower() for event in events if "api" in event)
    assert len(api_names) > 10
    api = facet_of(response, "api.name")
    assert api["total"] == sum(api_names.values())
    assert len(api["values"]) == 10
    assert [value["count"] for value in api["values"]] == sorted(api_names.values(), reverse=True)[
        :10
    ]
    assert all(value["count"] == api_names[value["value"]] for value in api["values"])
    lanes = facet_of(response, "lane")
    assert {value["value"]: value["count"] for value in lanes["values"]} == dict(
        Counter(event["tartarus"]["lane"] for event in events)
    )


@pytest.mark.parametrize(
    ("field", "term"),
    [
        ("process.name", "process.name"),
        ("process", "process.name"),
        ("tartarus.lane", "tartarus.lane"),
        ("event.action", "event.action"),
        ("api.name", "api.name"),
        ("destination.port", "destination.port"),
        ("event.severity", "event.severity"),
    ],
)
async def test_every_facet_count_equals_a_search_on_the_same_filter_plus_that_term(
    view_stack: ViewStack, field: str, term: str
) -> None:
    filters: dict[str, Any] = {"query": "NOT lane:registry"}

    response = await post_ok(view_stack, "facets", {"fields": [field], **filters})

    facet = facet_of(response, field)
    assert facet["values"]
    for value in facet["values"]:
        chip = {"field": term, "value": value["value"]}
        found = await count_matching(view_stack, filters=[chip], **filters)
        assert found == value["count"], value


async def test_the_facet_total_is_the_number_of_filtered_events_with_a_value(
    view_stack: ViewStack,
) -> None:
    filters: dict[str, Any] = {"lanes": ["network"]}

    response = await post_ok(view_stack, "facets", {"fields": ["process.name"], **filters})

    with_value = await count_matching(view_stack, query="process.name:*", **filters)
    assert facet_of(response, "process.name")["total"] == with_value


async def test_facets_follow_the_filter(view_stack: ViewStack) -> None:
    response = await post_ok(
        view_stack, "facets", {"fields": ["tartarus.lane"], "query": "lane:network"}
    )

    values = facet_of(response, "tartarus.lane")["values"]
    assert values == [{"value": "network", "count": 213}]


async def test_a_boolean_facet_reads_its_values_as_text(view_stack: ViewStack) -> None:
    response = await post_ok(view_stack, "facets", {"fields": ["api.status"]})

    values = {value["value"] for value in facet_of(response, "api.status")["values"]}
    assert values <= {"true", "false"}
    assert values


@pytest.mark.parametrize(
    "field", ["rule.description", "tartarus.raw", "api.arguments", "domain", "procss.name"]
)
async def test_a_field_that_cannot_be_a_facet_is_a_422(view_stack: ViewStack, field: str) -> None:
    response = await view_stack.client.post(
        events_url(view_stack, "facets"), json={"fields": [field]}
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_facet_field"


async def test_a_query_that_does_not_compile_is_a_422_with_spans(view_stack: ViewStack) -> None:
    response = await view_stack.client.post(events_url(view_stack, "facets"), json={"query": "x:("})

    assert response.status_code == 422
    assert response.json()["error"]["details"]["errors"]


async def test_an_analysis_with_no_index_has_empty_facets(view_stack: ViewStack) -> None:
    bare = await add_analysis_without_index(view_stack)

    response = await view_stack.client.post(
        events_url(view_stack, "facets", analysis_id=bare), json={"fields": ["process.name"]}
    )

    assert response.status_code == 200
    assert response.json() == {"facets": [{"field": "process.name", "values": [], "total": 0}]}


async def test_an_unknown_analysis_is_a_404(view_stack: ViewStack) -> None:
    response = await view_stack.client.post(
        events_url(view_stack, "facets", analysis_id=999_999), json={}
    )

    assert response.status_code == 404
