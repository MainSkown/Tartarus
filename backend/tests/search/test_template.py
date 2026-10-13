from typing import Any

from app.search.fields import FIELDS, FieldType
from app.search.template import INDEX_PREFIX, TEMPLATE_NAME, build_index_template

template = build_index_template()
mappings: dict[str, Any] = template["template"]["mappings"]
settings: dict[str, Any] = template["template"]["settings"]["index"]


def mapping_of(dotted_name: str) -> dict[str, Any]:
    node: dict[str, Any] = mappings
    for part in dotted_name.split("."):
        node = node["properties"][part]
    return node


def leaf_mappings(node: dict[str, Any], prefix: str = "") -> dict[str, dict[str, Any]]:
    leaves: dict[str, dict[str, Any]] = {}
    for key, child in node.get("properties", {}).items():
        path = f"{prefix}{key}"
        if "properties" in child:
            leaves.update(leaf_mappings(child, f"{path}."))
        else:
            leaves[path] = child
    return leaves


def test_template_targets_the_per_analysis_indices() -> None:
    assert TEMPLATE_NAME == "tartarus-events"
    assert template["index_patterns"] == [f"{INDEX_PREFIX}*"]
    assert INDEX_PREFIX == "tartarus-events-"
    assert template["priority"] == 100


def test_settings_follow_the_spec() -> None:
    assert settings["number_of_shards"] == 1
    assert settings["number_of_replicas"] == 0
    assert settings["codec"] == "best_compression"
    assert settings["refresh_interval"] == "1s"


def test_unknown_fields_are_not_indexed() -> None:
    assert mappings["dynamic"] is False


def test_lowercase_normalizer_is_defined() -> None:
    normalizer = template["template"]["settings"]["analysis"]["normalizer"]["lowercase"]
    assert normalizer == {"type": "custom", "filter": ["lowercase"]}


def test_every_catalog_field_is_mapped_and_nothing_else() -> None:
    mapped = leaf_mappings(mappings)
    assert sorted(mapped) == sorted(field.name for field in FIELDS)


def test_keyword_fields_are_lowercased_and_bounded() -> None:
    mapping = mapping_of("process.name")
    assert mapping["type"] == "keyword"
    assert mapping["normalizer"] == "lowercase"
    assert mapping["ignore_above"] > 0


def test_every_keyword_typed_field_has_the_normalizer() -> None:
    keywords = [
        f.name for f in FIELDS if f.type in (FieldType.KEYWORD, FieldType.KEYWORD_WITH_TEXT)
    ]
    assert keywords
    assert [n for n in keywords if mapping_of(n).get("normalizer") != "lowercase"] == []


def test_path_command_line_and_summary_fields_have_a_text_subfield() -> None:
    for name in ("file.path", "process.executable", "process.command_line", "tartarus.summary"):
        mapping = mapping_of(name)
        assert mapping["type"] == "keyword"
        assert mapping["normalizer"] == "lowercase"
        assert mapping["fields"]["text"] == {"type": "text"}


def test_plain_keywords_have_no_text_subfield() -> None:
    assert "fields" not in mapping_of("process.name")


def test_raw_record_is_kept_but_not_indexed() -> None:
    assert mapping_of("tartarus.raw") == {"type": "object", "enabled": False}


def test_api_arguments_is_a_flat_object() -> None:
    assert mapping_of("api.arguments") == {"type": "flat_object"}


def test_numeric_date_ip_and_boolean_fields_map_to_their_native_types() -> None:
    assert mapping_of("process.pid") == {"type": "long"}
    assert mapping_of("event.severity") == {"type": "integer"}
    assert mapping_of("destination.ip") == {"type": "ip"}
    assert mapping_of("api.status") == {"type": "boolean"}
    assert mapping_of("@timestamp")["type"] == "date"
    assert mapping_of("rule.description") == {"type": "text"}


def test_every_call_builds_an_independent_body() -> None:
    first = build_index_template()
    first["template"]["mappings"]["dynamic"] = True
    assert build_index_template()["template"]["mappings"]["dynamic"] is False
