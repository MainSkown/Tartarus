from collections import Counter
from typing import Any

import pytest

from tests.integration.events.conftest import all_events
from tests.integration.views.conftest import ViewStack
from tests.integration.views.helpers import add_analysis_without_index

pytestmark = pytest.mark.integration


async def values_of(stack: ViewStack, **params: Any) -> list[dict[str, Any]]:
    response = await stack.client.get(
        f"/api/analyses/{stack.analysis_id}/query/values", params=params
    )
    assert response.status_code == 200, response.text
    values: list[dict[str, Any]] = response.json()["values"]
    return values


async def test_values_are_the_prefix_matches_most_common_first(view_stack: ViewStack) -> None:
    events = await all_events(view_stack)
    names = Counter(event["api"]["name"].lower() for event in events if "api" in event)
    expected = {name: n for name, n in names.items() if name.startswith("ntq")}

    values = await values_of(view_stack, field="api.name", prefix="ntq", limit=50)

    assert expected
    assert {value["value"]: value["count"] for value in values} == expected
    assert [value["count"] for value in values] == sorted(expected.values(), reverse=True)


@pytest.mark.parametrize("prefix", ["NTQ", "nTq", "ntq"])
async def test_the_prefix_matches_whatever_its_case(view_stack: ViewStack, prefix: str) -> None:
    values = await values_of(view_stack, field="api", prefix=prefix)

    assert values
    assert all(value["value"].startswith("ntq") for value in values)


async def test_the_values_are_capped_by_the_limit_and_default_to_ten(view_stack: ViewStack) -> None:
    assert len(await values_of(view_stack, field="api.name")) == 10
    assert len(await values_of(view_stack, field="api.name", limit=3)) == 3


async def test_a_prefix_with_regex_characters_is_taken_literally(view_stack: ViewStack) -> None:
    assert await values_of(view_stack, field="api.name", prefix=".*") == []
    assert await values_of(view_stack, field="api.name", prefix="nt(") == []


async def test_a_path_prefix_with_backslashes_matches(view_stack: ViewStack) -> None:
    events = await all_events(view_stack)
    paths = {
        event["process"]["executable"].lower()
        for event in events
        if "executable" in event.get("process", {})
    }
    prefix = "C:\\Users\\Analyst".upper()

    values = await values_of(view_stack, field="process.executable", prefix=prefix)

    assert {value["value"] for value in values} == {
        p for p in paths if p.startswith(prefix.lower())
    }
    assert values


async def test_the_domain_alias_merges_dns_names_and_destination_domains(
    view_stack: ViewStack,
) -> None:
    events = await all_events(view_stack)
    expected: Counter[str] = Counter()
    for event in events:
        expected[event.get("dns", {}).get("question", {}).get("name", "").lower()] += 1
        expected[event.get("destination", {}).get("domain", "").lower()] += 1
    del expected[""]

    values = await values_of(view_stack, field="domain", limit=50)

    assert expected
    assert {value["value"]: value["count"] for value in values} == dict(expected)


@pytest.mark.parametrize("field", ["process.pid", "rule.description", "api.arguments", "nope"])
async def test_a_field_that_is_not_a_keyword_is_a_422(view_stack: ViewStack, field: str) -> None:
    response = await view_stack.client.get(
        f"/api/analyses/{view_stack.analysis_id}/query/values", params={"field": field}
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_value_field"


@pytest.mark.parametrize("limit", [0, 51])
async def test_a_limit_out_of_range_is_a_422(view_stack: ViewStack, limit: int) -> None:
    response = await view_stack.client.get(
        f"/api/analyses/{view_stack.analysis_id}/query/values",
        params={"field": "api.name", "limit": limit},
    )

    assert response.status_code == 422


async def test_a_missing_field_is_a_422(view_stack: ViewStack) -> None:
    response = await view_stack.client.get(f"/api/analyses/{view_stack.analysis_id}/query/values")

    assert response.status_code == 422


async def test_an_unknown_analysis_is_a_404(view_stack: ViewStack) -> None:
    response = await view_stack.client.get(
        "/api/analyses/999999/query/values", params={"field": "api.name"}
    )

    assert response.status_code == 404


async def test_an_analysis_with_no_index_has_no_values(view_stack: ViewStack) -> None:
    bare = await add_analysis_without_index(view_stack)

    response = await view_stack.client.get(
        f"/api/analyses/{bare}/query/values", params={"field": "api.name"}
    )

    assert response.status_code == 200
    assert response.json() == {"values": []}
