import pytest
from pydantic import ValidationError

from app.errors import ApiError
from app.events.columns import resolve_columns
from app.schemas.events_api import MAX_COLUMNS, SearchRequest


def refused(columns: list[str]) -> ApiError:
    with pytest.raises(ApiError) as caught:
        resolve_columns(columns)
    assert caught.value.status_code == 422
    assert caught.value.code == "invalid_column"
    return caught.value


def test_a_column_is_a_catalog_field_by_its_canonical_name() -> None:
    assert resolve_columns(["process.command_line", "file.hash.sha256"]) == [
        "process.command_line",
        "file.hash.sha256",
    ]


def test_an_alias_is_keyed_by_the_canonical_name_and_a_repeat_is_collapsed() -> None:
    columns = resolve_columns(["cmdline", "process.command_line", "CMD", "pid"])

    assert columns == ["process.command_line", "process.pid"]


@pytest.mark.parametrize("field", ["rule.description", "api.arguments", "event.severity"])
def test_text_flat_object_and_number_fields_can_be_columns(field: str) -> None:
    assert resolve_columns([field]) == [field]


@pytest.mark.parametrize(
    "field", ["nope.field", "domain", "tartarus.raw", "api.arguments.FileName"]
)
def test_a_field_that_cannot_be_shown_is_refused_and_named(field: str) -> None:
    assert field in refused([field]).message


def test_an_unknown_column_is_refused_with_a_suggestion() -> None:
    assert "did you mean 'process.command_line'" in refused(["process.command_lin"]).message


def test_a_composite_alias_names_its_members() -> None:
    message = refused(["domain"]).message

    assert "dns.question.name" in message
    assert "destination.domain" in message


def test_no_columns_is_no_fields() -> None:
    assert resolve_columns([]) == []


def test_more_than_the_limit_of_columns_is_a_validation_error() -> None:
    too_many = [f"process.pid{n}" for n in range(MAX_COLUMNS + 1)]

    with pytest.raises(ValidationError):
        SearchRequest(columns=too_many)
