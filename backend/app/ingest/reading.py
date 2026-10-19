"""Defensive readers for report fields whose type CAPE does not guarantee."""

import re
from collections.abc import Mapping
from typing import Any

NON_ASCII = re.compile(r"[^\x00-\x7f]")


def to_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if not isinstance(value, str):
        return None
    text = value.strip()
    try:
        return int(text, 16 if text.lower().startswith("0x") else 10)
    except ValueError:
        return None


def text_or_none(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def mapping_list(value: object) -> list[Mapping[str, Any]]:
    return [item for item in value if isinstance(item, Mapping)] if isinstance(value, list) else []


def section(report: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    value = report.get(key)
    return value if isinstance(value, Mapping) else {}


def sample_file_name(report: Mapping[str, Any]) -> str | None:
    """The sample's file name as the guest has it: each non-ASCII character is an `_`."""
    name = text_or_none(section(section(report, "target"), "file").get("name"))
    return None if name is None else NON_ASCII.sub("_", name)
