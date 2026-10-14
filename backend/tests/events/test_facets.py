from typing import Any

import pytest

from app.errors import ApiError
from app.events.facets import build_facets_body, read_facets_response
from app.schemas.events_api import DEFAULT_FACET_FIELDS, FacetsRequest, ValueCount


def refused(fields: list[str]) -> ApiError:
    with pytest.raises(ApiError) as caught:
        build_facets_body(FacetsRequest(fields=fields))
    assert caught.value.status_code == 422
    assert caught.value.code == "invalid_facet_field"
    return caught.value


def test_each_field_gets_a_top_ten_terms_aggregation_and_a_count_of_events_with_a_value() -> None:
    body = build_facets_body(FacetsRequest(fields=["process.name", "lane"]))

    assert body["size"] == 0
    assert body["aggs"] == {
        "values_0": {"terms": {"field": "process.name", "size": 10}},
        "present_0": {"filter": {"exists": {"field": "process.name"}}},
        "values_1": {"terms": {"field": "tartarus.lane", "size": 10}},
        "present_1": {"filter": {"exists": {"field": "tartarus.lane"}}},
    }


def test_the_facets_are_computed_on_the_filtered_set() -> None:
    body = build_facets_body(FacetsRequest(query="lane:file", fields=["process.name"]))

    assert body["query"] == {"bool": {"filter": [{"term": {"tartarus.lane": "file"}}]}}


def test_without_fields_the_default_ones_are_used() -> None:
    body = build_facets_body(FacetsRequest())

    paths = [
        agg["terms"]["field"] for name, agg in body["aggs"].items() if name.startswith("values")
    ]
    assert paths == DEFAULT_FACET_FIELDS


@pytest.mark.parametrize(
    "field",
    ["rule.description", "tartarus.raw", "api.arguments", "api.arguments.FileName"],
)
def test_a_field_that_cannot_be_aggregated_is_refused(field: str) -> None:
    assert field in refused([field]).message


def test_a_composite_alias_is_refused_with_its_members_named() -> None:
    message = refused(["domain"]).message

    assert "dns.question.name" in message
    assert "destination.domain" in message


def test_an_unknown_field_is_refused_with_a_suggestion() -> None:
    assert "did you mean 'process.name'" in refused(["procss.name"]).message


def facets_response() -> dict[str, Any]:
    return {
        "aggregations": {
            "values_0": {
                "buckets": [{"key": "cmd.exe", "doc_count": 5}, {"key": "a", "doc_count": 2}]
            },
            "present_0": {"doc_count": 7},
            "values_1": {
                "buckets": [
                    {"key": 1, "key_as_string": "true", "doc_count": 3},
                    {"key": 80, "doc_count": 1},
                ]
            },
            "present_1": {"doc_count": 4},
        }
    }


def test_the_response_lists_each_field_as_requested_with_its_values_and_total() -> None:
    facets = read_facets_response(["process", "api.status"], facets_response()).facets

    assert [facet.field for facet in facets] == ["process", "api.status"]
    assert facets[0].values == [
        ValueCount(value="cmd.exe", count=5),
        ValueCount(value="a", count=2),
    ]
    assert facets[0].total == 7
    assert facets[1].values == [ValueCount(value="true", count=3), ValueCount(value="80", count=1)]


def test_an_analysis_with_no_events_has_empty_facets() -> None:
    facets = read_facets_response(["process.name"], {"aggregations": {}}).facets

    assert (facets[0].values, facets[0].total) == ([], 0)
