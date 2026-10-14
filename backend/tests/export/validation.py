import json
import re
from pathlib import Path
from typing import Any

import stix2
from jsonschema import Draft4Validator

# event-2.5.schema.json is the MISP project's own schema for exported events, unmodified:
# https://github.com/MISP/MISP/blob/bf12c5700afa6f60fb67d6bd69c649ff503d2ec6/format/2.5/schema.json
# It constrains types and unknown keys but requires nothing, so the required keys and the
# (type, category) pairs MISP accepts are checked here, from MISP's documented defaults.
MISP_SCHEMA = Path(__file__).parent.parent / "fixtures" / "misp" / "event-2.5.schema.json"
EVENT_REQUIRED = ("info", "uuid", "date", "timestamp", "Attribute", "Tag")
ATTRIBUTE_REQUIRED = ("type", "category", "value", "to_ids", "uuid", "timestamp")
ALLOWED_CATEGORIES = {
    "sha256": {
        "Payload delivery",
        "Artifacts dropped",
        "Payload installation",
        "External analysis",
    },
    "sha1": {"Payload delivery", "Artifacts dropped", "Payload installation", "External analysis"},
    "md5": {"Payload delivery", "Artifacts dropped", "Payload installation", "External analysis"},
    "domain": {"Network activity", "Payload delivery", "External analysis"},
    "ip-dst": {"Network activity", "Payload delivery", "External analysis"},
    "url": {"Network activity", "Payload delivery", "External analysis"},
    "filename": {
        "Payload delivery",
        "Artifacts dropped",
        "Payload installation",
        "Persistence mechanism",
    },
    "regkey": {
        "Persistence mechanism",
        "Artifacts dropped",
        "Payload installation",
        "External analysis",
    },
    "mutex": {"Artifacts dropped", "Payload installation", "External analysis"},
    "comment": {"Other", "External analysis", "Internal reference"},
}
UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


def parse_stix(bundle: dict[str, Any]) -> stix2.v21.Bundle:
    """The reference parser, strict: custom properties and objects are errors."""
    parsed = stix2.parse(bundle, allow_custom=False)
    assert isinstance(parsed, stix2.v21.Bundle)
    return parsed


def misp_problems(document: dict[str, Any]) -> list[str]:
    schema = json.loads(MISP_SCHEMA.read_text())
    problems = [error.message for error in Draft4Validator(schema).iter_errors(document)]
    event = document.get("Event", {})
    problems += [f"event lacks {key}" for key in EVENT_REQUIRED if key not in event]
    seen: set[tuple[str, str]] = set()
    for attribute in event.get("Attribute", []):
        problems += [f"attribute lacks {key}" for key in ATTRIBUTE_REQUIRED if key not in attribute]
        problems += _attribute_problems(attribute)
        key = (attribute.get("type", ""), attribute.get("value", ""))
        problems += [f"duplicate attribute {key}"] if key in seen else []
        seen.add(key)
    return problems


def _attribute_problems(attribute: dict[str, Any]) -> list[str]:
    problems = []
    allowed = ALLOWED_CATEGORIES.get(attribute.get("type", ""))
    if allowed is None or attribute.get("category") not in allowed:
        problems.append(f"{attribute.get('type')} cannot be in {attribute.get('category')}")
    if not UUID.fullmatch(attribute.get("uuid", "")):
        problems.append(f"bad attribute uuid {attribute.get('uuid')}")
    if not str(attribute.get("timestamp", "")).isdigit():
        problems.append("attribute timestamp is not epoch seconds as a string")
    return problems
