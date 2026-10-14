"""The compiler reads the field catalog; these tests keep it in step with the index template."""

from typing import Any

import pytest

from app.query.clauses import FREE_TEXT_FIELDS
from app.query.compiler import compile_query
from app.search.fields import FIELDS, TEXT_SUBFIELD, FieldType, field_by_name
from app.search.template import build_index_template

SEARCHABLE = [field for field in FIELDS if field.type is not FieldType.OBJECT_DISABLED]


def mapping_of(path: str) -> dict[str, Any]:
    node: dict[str, Any] = build_index_template()["template"]["mappings"]
    *parents, leaf = path.split(".")
    properties = node["properties"]
    for parent in parents:
        properties = properties[parent]["properties"]
    return dict(properties[leaf])


def test_the_text_subfield_name_is_the_one_the_index_template_builds() -> None:
    mapping = mapping_of("file.path")
    assert mapping["fields"][TEXT_SUBFIELD] == {"type": "text"}


@pytest.mark.parametrize("field", [f for f in FIELDS if f.type is FieldType.KEYWORD_WITH_TEXT])
def test_every_keyword_with_text_field_has_the_text_subfield_in_the_template(field: Any) -> None:
    assert TEXT_SUBFIELD in mapping_of(field.name)["fields"]


@pytest.mark.parametrize("name", FREE_TEXT_FIELDS)
def test_free_text_fields_are_catalog_fields_a_wildcard_can_reach(name: str) -> None:
    assert field_by_name(name).type in {
        FieldType.KEYWORD,
        FieldType.KEYWORD_WITH_TEXT,
        FieldType.FLAT_OBJECT,
    }


@pytest.mark.parametrize("field", SEARCHABLE, ids=lambda field: field.name)
def test_every_searchable_catalog_field_accepts_its_own_example_value(field: Any) -> None:
    quoted = field.example.replace("\\", "\\\\").replace('"', '\\"')
    compiled = compile_query(f'{field.name}:"{quoted}"')
    assert compiled.errors == []


@pytest.mark.parametrize("field", SEARCHABLE, ids=lambda field: field.name)
def test_every_searchable_catalog_field_and_alias_has_an_exists_query(field: Any) -> None:
    for name in (field.name, *field.aliases):
        assert compile_query(f"{name}:*").query == {"exists": {"field": field.name}}


def test_the_raw_record_is_the_only_catalog_field_the_compiler_refuses() -> None:
    refused = [f.name for f in FIELDS if not compile_query(f"{f.name}:*").ok]
    assert refused == ["tartarus.raw"]
