import copy
import json
import re
from collections.abc import Mapping
from typing import Any

from app.ingest.ecs import LANES
from app.ingest.protocol import IngestContext, Normalizer

TIMESTAMP = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")
EVENT_ID = re.compile(r"^[0-9a-f]{40}$")


def check_normalizer_contract(
    normalizer: Normalizer, report: Mapping[str, Any], context: IngestContext
) -> list[dict[str, Any]]:
    """Asserts what every normaliser promises; returns the events for further checks."""
    assert isinstance(normalizer, Normalizer)
    assert normalizer.source
    untouched = copy.deepcopy(report)
    events = list(normalizer.normalise(report, context))
    assert report == untouched, "normalise mutated the report"
    assert events, "a real report must yield events"
    assert events == list(normalizer.normalise(report, context)), "output is not deterministic"
    for event in events:
        check_common_fields(event, context)
    assert_unique_ids(events)
    assert_increasing_sequence(events)
    return events


def check_common_fields(event: Mapping[str, Any], context: IngestContext) -> None:
    json.dumps(event)
    assert TIMESTAMP.match(event["@timestamp"])
    meta = event["event"]
    assert EVENT_ID.match(meta["id"])
    assert meta["kind"] in {"event", "alert"}
    assert meta["category"]
    assert meta["type"]
    assert all(isinstance(value, str) and value for value in (meta["action"], meta["dataset"]))
    assert meta["module"]
    assert meta["severity"] in range(5)
    tartarus = event["tartarus"]
    assert tartarus["analysis_id"] == context.analysis_id
    assert tartarus["lane"] in LANES
    assert tartarus["phase"] == "final"
    assert tartarus["summary"]
    assert "raw" in tartarus


def assert_unique_ids(events: list[dict[str, Any]]) -> None:
    ids = [event["event"]["id"] for event in events]
    assert len(set(ids)) == len(ids)


def assert_increasing_sequence(events: list[dict[str, Any]]) -> None:
    sequence = [event["event"]["sequence"] for event in events]
    assert sequence == sorted(set(sequence))


def check_tolerates_junk(normalizer: Normalizer, context: IngestContext) -> None:
    for junk in ({}, {"behavior": None}, {"behavior": {"processes": "x"}}, {"behavior": []}):
        for event in normalizer.normalise(junk, context):
            check_common_fields(event, context)
