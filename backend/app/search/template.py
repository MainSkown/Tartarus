from typing import Any

from app.search.fields import FIELDS, FieldDefinition, FieldType

TEMPLATE_NAME = "tartarus-events"
INDEX_PREFIX = f"{TEMPLATE_NAME}-"

# Lucene rejects a term over 32766 bytes; staying under keeps one oversized value from failing
# the whole document. The value stays in _source, and for text-backed fields in the text subfield.
KEYWORD_IGNORE_ABOVE = 8191

_KEYWORD: dict[str, Any] = {
    "type": "keyword",
    "normalizer": "lowercase",
    "ignore_above": KEYWORD_IGNORE_ABOVE,
}

_SIMPLE_MAPPINGS: dict[FieldType, dict[str, Any]] = {
    FieldType.TEXT: {"type": "text"},
    FieldType.LONG: {"type": "long"},
    FieldType.INTEGER: {"type": "integer"},
    FieldType.DATE: {"type": "date", "format": "strict_date_optional_time||epoch_millis"},
    FieldType.IP: {"type": "ip"},
    FieldType.BOOLEAN: {"type": "boolean"},
    FieldType.FLAT_OBJECT: {"type": "flat_object"},
    FieldType.OBJECT_DISABLED: {"type": "object", "enabled": False},
}


def _field_mapping(field: FieldDefinition) -> dict[str, Any]:
    if field.type is FieldType.KEYWORD:
        return dict(_KEYWORD)
    if field.type is FieldType.KEYWORD_WITH_TEXT:
        return {**_KEYWORD, "fields": {"text": {"type": "text"}}}
    return dict(_SIMPLE_MAPPINGS[field.type])


def _nested_properties(fields: tuple[FieldDefinition, ...]) -> dict[str, Any]:
    root: dict[str, Any] = {}
    for field in fields:
        *parents, leaf = field.name.split(".")
        properties = root
        for parent in parents:
            properties = properties.setdefault(parent, {"properties": {}})["properties"]
        properties[leaf] = _field_mapping(field)
    return root


def build_index_template() -> dict[str, Any]:
    return {
        "index_patterns": [f"{INDEX_PREFIX}*"],
        "priority": 100,
        "template": {
            "settings": {
                "index": {
                    "number_of_shards": 1,
                    "number_of_replicas": 0,
                    "codec": "best_compression",
                    "refresh_interval": "1s",
                },
                "analysis": {
                    "normalizer": {"lowercase": {"type": "custom", "filter": ["lowercase"]}}
                },
            },
            "mappings": {"dynamic": False, "properties": _nested_properties(FIELDS)},
        },
    }
