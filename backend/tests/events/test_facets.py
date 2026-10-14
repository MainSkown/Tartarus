from typing import Any

import pytest

from app.errors import ApiError
from app.events.facets import build_facets_body, read_facets_response
from app.events.filters import filter_query
from app.schemas.events_api import DEFAULT_FACET_FIELDS, FacetsRequest, FilterChip, ValueCount


def refused(fields: list[str]) -> ApiError:
    with pytest.raises(ApiError) as caught:
        build_facets_body(FacetsRequest(fields=fields))
    assert caught.value.status_code == 422
    assert caught.value.code == "invalid_facet_field"
    return caught.value


def chip(field: str, value: str, negate: bool = False) -> FilterChip:
    return FilterChip(field=field, value=value, negate=negate)


def term(path: str, value: str) -> dict[str, Any]:
    return {"term": {path: value}}


def counted(path: str, chips: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "filter": chips or {"match_all": {}},
        "aggs": {
            "values": {"terms": {"field": path, "size": 10}},
            "present": {"filter": {"exists": {"field": path}}},
        },
    }


def test_each_field_gets_a_top_ten_terms_aggregation_and_a_count_of_events_with_a_value() -> None:
    body = build_facets_body(FacetsRequest(fields=["process.name", "lane"]))

    assert body["size"] == 0
    assert body["aggs"] == {
        "facet_0": counted("process.name"),
        "facet_1": counted("tartarus.lane"),
    }


def test_the_facets_are_computed_on_the_filtered_set() -> None:
    body = build_facets_body(FacetsRequest(query="lane:file", fields=["process.name"]))

    assert body["query"] == {"bool": {"filter": [term("tartarus.lane", "file")]}}


def test_without_chips_the_query_is_the_whole_filter_as_before() -> None:
    request = FacetsRequest(query="lane:file", lanes=None, pids=[4], fields=["process.name"])

    assert build_facets_body(request)["query"] == filter_query(request)


def test_a_chip_on_a_facet_field_is_left_out_of_that_facet_and_out_of_the_query() -> None:
    body = build_facets_body(
        FacetsRequest(filters=[chip("process.name", "cmd.exe")], fields=["process.name", "lane"])
    )

    assert body["query"] == {"match_all": {}}
    assert body["aggs"]["facet_0"] == counted("process.name")
    assert body["aggs"]["facet_1"] == counted(
        "tartarus.lane", {"bool": {"filter": [term("process.name", "cmd.exe")]}}
    )


def test_a_chip_named_by_an_alias_counts_as_the_field_it_resolves_to() -> None:
    body = build_facets_body(
        FacetsRequest(
            filters=[chip("proc", "cmd.exe"), chip("lane", "api")], fields=["process.name", "lane"]
        )
    )

    assert body["aggs"]["facet_0"]["filter"] == {"bool": {"filter": [term("tartarus.lane", "api")]}}
    assert body["aggs"]["facet_1"]["filter"] == {
        "bool": {"filter": [term("process.name", "cmd.exe")]}
    }


def test_a_negated_chip_is_left_out_of_its_own_facet_but_still_excludes_in_the_others() -> None:
    body = build_facets_body(
        FacetsRequest(
            filters=[chip("process.name", "cmd.exe", negate=True)], fields=["process.name", "lane"]
        )
    )

    assert body["aggs"]["facet_0"]["filter"] == {"match_all": {}}
    assert body["aggs"]["facet_1"]["filter"] == {
        "bool": {"must_not": [term("process.name", "cmd.exe")]}
    }


def test_a_chip_on_a_field_that_is_not_a_facet_stays_in_the_query() -> None:
    body = build_facets_body(
        FacetsRequest(filters=[chip("file.path", "*.exe")], fields=["process.name"])
    )

    assert body["query"] != {"match_all": {}}
    assert body["aggs"]["facet_0"]["filter"] == {"match_all": {}}


def test_the_query_text_and_the_other_restrictions_apply_to_every_facet() -> None:
    body = build_facets_body(
        FacetsRequest(
            query="lane:file",
            pids=[4],
            filters=[chip("process.name", "cmd.exe")],
            fields=["process.name"],
        )
    )

    assert body["query"] == {
        "bool": {"filter": [term("tartarus.lane", "file"), {"terms": {"process.pid": [4]}}]}
    }


def test_a_chip_on_a_composite_alias_is_left_out_of_the_facet_of_each_member() -> None:
    body = build_facets_body(
        FacetsRequest(
            filters=[chip("domain", "a.example")], fields=["destination.domain", "process.name"]
        )
    )

    assert body["aggs"]["facet_0"]["filter"] == {"match_all": {}}
    assert body["aggs"]["facet_1"]["filter"]["bool"]["filter"][0]["bool"]["should"]


def test_a_bad_chip_is_refused_once_with_its_index() -> None:
    request = FacetsRequest(
        filters=[chip("process.name", "cmd.exe"), chip("process.pid", "abc")],
        fields=["process.name", "process.pid", "lane"],
    )

    with pytest.raises(ApiError) as caught:
        build_facets_body(request)

    assert caught.value.code == "invalid_query"
    assert [error["filter_index"] for error in caught.value.details["errors"]] == [1]


def test_without_fields_the_default_ones_are_used() -> None:
    body = build_facets_body(FacetsRequest())

    paths = [facet["aggs"]["values"]["terms"]["field"] for facet in body["aggs"].values()]
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
            "facet_0": {
                "values": {
                    "buckets": [{"key": "cmd.exe", "doc_count": 5}, {"key": "a", "doc_count": 2}]
                },
                "present": {"doc_count": 7},
            },
            "facet_1": {
                "values": {
                    "buckets": [
                        {"key": 1, "key_as_string": "true", "doc_count": 3},
                        {"key": 80, "doc_count": 1},
                    ]
                },
                "present": {"doc_count": 4},
            },
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
