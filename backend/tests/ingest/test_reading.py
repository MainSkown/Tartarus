from typing import Any

import pytest

from app.ingest.reading import mapping_list, section, text_or_none, to_int


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (5, 5),
        ("12", 12),
        (" 7 ", 7),
        ("0x1f", 31),
        (True, None),
        (1.5, None),
        ("x", None),
        (None, None),
    ],
)
def test_to_int_reads_decimal_and_hex_and_nothing_else(value: object, expected: int | None) -> None:
    assert to_int(value) == expected


@pytest.mark.parametrize(("value", "expected"), [("a", "a"), ("", None), (3, None), (None, None)])
def test_text_or_none_keeps_only_non_empty_text(value: object, expected: str | None) -> None:
    assert text_or_none(value) == expected


def test_mapping_list_keeps_the_mappings_of_a_list() -> None:
    assert mapping_list([{"a": 1}, None, 3, {"b": 2}]) == [{"a": 1}, {"b": 2}]


@pytest.mark.parametrize("value", [None, "x", {"a": 1}, 4])
def test_mapping_list_of_anything_but_a_list_is_empty(value: object) -> None:
    assert mapping_list(value) == []


def test_section_reads_a_mapping_below_a_report_key() -> None:
    assert section({"network": {"dns": []}}, "network") == {"dns": []}


@pytest.mark.parametrize("report", [{}, {"network": None}, {"network": []}, {"network": "x"}])
def test_section_is_empty_when_the_key_is_not_a_mapping(report: dict[str, Any]) -> None:
    assert section(report, "network") == {}
