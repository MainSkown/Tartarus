from typing import Any

import pytest
from fastapi import FastAPI

RESPONSE_MODELS = [
    "Event",
    "EventProcess",
    "EventDestination",
    "EventPage",
    "Facet",
    "FacetsResponse",
    "ValueCount",
    "Histogram",
    "HistogramBucket",
    "HistogramDetection",
    "EventDetail",
    "RelatedEvents",
    "QueryValidation",
    "QueryErrorRead",
    "FieldRead",
    "FieldValues",
]


@pytest.fixture
def schema(app: FastAPI) -> dict[str, Any]:
    return app.openapi()


@pytest.mark.parametrize("model", RESPONSE_MODELS)
def test_every_field_of_a_response_model_is_required_so_the_client_never_guesses(
    schema: dict[str, Any], model: str
) -> None:
    definition = schema["components"]["schemas"][model]

    assert set(definition["required"]) == set(definition["properties"])


def test_the_listing_of_related_events_is_required_too(schema: dict[str, Any]) -> None:
    listing = next(
        definition
        for name, definition in schema["components"]["schemas"].items()
        if name.startswith("Listing") and "Event" in name
    )

    assert set(listing["required"]) == {"items", "total"}


def test_the_histogram_names_its_ends_from_and_to(schema: dict[str, Any]) -> None:
    properties = schema["components"]["schemas"]["Histogram"]["properties"]

    assert {"from", "to", "interval_ms", "buckets", "detections", "total"} == set(properties)


def test_the_time_range_is_sent_as_from_and_to(schema: dict[str, Any]) -> None:
    assert set(schema["components"]["schemas"]["TimeRange"]["properties"]) == {"from", "to"}


def test_the_endpoints_are_documented_under_api_with_readable_operation_ids(
    schema: dict[str, Any],
) -> None:
    operations = {
        (path, method): operation["operationId"]
        for path, methods in schema["paths"].items()
        for method, operation in methods.items()
    }

    assert operations[("/api/analyses/{analysis_id}/events/search", "post")] == "events_search"
    assert operations[("/api/analyses/{analysis_id}/events/facets", "post")] == "events_facets"
    assert (
        operations[("/api/analyses/{analysis_id}/events/histogram", "post")] == "events_histogram"
    )
    assert operations[("/api/analyses/{analysis_id}/events/{event_id}", "get")] == "events_detail"
    assert operations[("/api/query/validate", "post")] == "query_validate"
    assert operations[("/api/query/fields", "get")] == "query_fields"
    assert operations[("/api/analyses/{analysis_id}/query/values", "get")] == "query_values"


def test_the_values_parameters_are_query_parameters(schema: dict[str, Any]) -> None:
    operation = schema["paths"]["/api/analyses/{analysis_id}/query/values"]["get"]

    located = {(p["name"], p["in"]) for p in operation["parameters"]}
    assert located == {
        ("analysis_id", "path"),
        ("field", "query"),
        ("prefix", "query"),
        ("limit", "query"),
    }


def test_the_columns_of_an_event_are_a_map_of_a_recursive_json_value(
    schema: dict[str, Any],
) -> None:
    schemas = schema["components"]["schemas"]

    assert schemas["Event"]["properties"]["fields"]["additionalProperties"] == {
        "$ref": "#/components/schemas/JsonValue"
    }
    assert "JsonValue" in schemas
