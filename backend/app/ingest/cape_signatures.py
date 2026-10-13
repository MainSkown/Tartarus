import json
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from app.ingest.capemon import api_event_id, call_lane, read_calls
from app.ingest.capemon_calls import Call
from app.ingest.clock import analysis_ended
from app.ingest.ecs import EventFactory, EventShape, SourceRecord, related_events, severity_level
from app.ingest.protocol import IngestContext
from app.ingest.reading import mapping_list, text_or_none, to_int

SOURCE = "cape-signatures"
MODULE = "cape"
DATASET = "cape.signature"
SOURCE_FILE = "signatures"
MATCH_LIMIT = 300
ELLIPSIS = "…"

CallKey = tuple[int, int]


def _shape(lane: str) -> EventShape:
    return EventShape("signature-matched", ("malware",), ("indicator",), lane, DATASET, "alert")


@dataclass(frozen=True)
class _Candidate:
    record: SourceRecord
    shape: EventShape
    summary: str
    severity: int
    sections: dict[str, Any]
    match: str | None


@dataclass(frozen=True)
class _ReportFacts:
    """What every signature of one report is resolved against."""

    calls: Mapping[CallKey, Call]
    techniques: Mapping[str, list[str]]
    fallback_time: datetime
    analysis_id: int


class CapeSignaturesNormalizer:
    """Turns `signatures` into alert events, with ATT&CK ids from `ttps`.

    Time, lane and reference rules: docs/specs/data-model.md, "CAPE report normalisers (as built)".
    """

    source = SOURCE

    def normalise(
        self, report: Mapping[str, Any], context: IngestContext
    ) -> Iterator[dict[str, Any]]:
        facts = _ReportFacts(
            calls=_calls_by_reference(read_calls(report, context)),
            techniques=_techniques_by_signature(report.get("ttps")),
            fallback_time=analysis_ended(report) or context.started_at,
            analysis_id=context.analysis_id,
        )
        candidates = [
            candidate
            for index, entry in enumerate(mapping_list(report.get("signatures")))
            if (candidate := _candidate(entry, index, facts))
        ]
        factory = EventFactory(context, source=SOURCE, source_file=SOURCE_FILE, module=MODULE)
        for candidate in sorted(candidates, key=lambda c: c.record.timestamp):
            tartarus = {"detection": {"match": candidate.match}} if candidate.match else None
            yield factory.build(
                candidate.shape,
                candidate.record,
                candidate.summary,
                severity=candidate.severity,
                tartarus=tartarus,
                **candidate.sections,
            )


def _calls_by_reference(calls: list[Call]) -> dict[CallKey, Call]:
    by_reference: dict[CallKey, Call] = {}
    for call in calls:
        call_id = to_int(call.raw.get("id"))
        if call_id is not None:
            by_reference.setdefault((call.process.pid, call_id), call)
    return by_reference


def _techniques_by_signature(ttps: object) -> dict[str, list[str]]:
    by_signature: dict[str, list[str]] = {}
    for entry in mapping_list(ttps):
        name = text_or_none(entry.get("signature"))
        identifiers = entry.get("ttps")
        if name is None or not isinstance(identifiers, list):
            continue
        known = by_signature.setdefault(name, [])
        known.extend(i for i in dict.fromkeys(_texts(identifiers)) if i not in known)
    return by_signature


def _texts(values: object) -> list[str]:
    items = values if isinstance(values, list) else []
    return [text for value in items if (text := text_or_none(value))]


def _reference(entry: Mapping[str, Any]) -> CallKey | None:
    pid, call_id = to_int(entry.get("pid")), to_int(entry.get("cid"))
    is_call = entry.get("type") == "call"
    return (pid, call_id) if is_call and pid is not None and call_id is not None else None


def _referenced_calls(data: object, calls: Mapping[CallKey, Call]) -> list[Call]:
    references = dict.fromkeys(key for entry in mapping_list(data) if (key := _reference(entry)))
    return [calls[key] for key in references if key in calls]


def _match_text(data: object) -> str | None:
    pieces: dict[str, None] = {}
    for entry in mapping_list(data):
        if entry.get("type") != "call":
            pieces.update(
                dict.fromkeys(f"{key}: {_as_text(value)}" for key, value in entry.items())
            )
    text = "; ".join(pieces)
    if len(text) > MATCH_LIMIT:
        text = text[: MATCH_LIMIT - len(ELLIPSIS)] + ELLIPSIS
    return text or None


def _pieces(entry: Mapping[str, Any]) -> Iterator[str]:
    return (f"{key}: {_as_text(value)}" for key, value in entry.items())


def _as_text(value: object) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False, default=str)


def _rule(entry: Mapping[str, Any], name: str) -> dict[str, Any]:
    rule: dict[str, Any] = {"name": name, "ruleset": "cape"}
    if description := text_or_none(entry.get("description")):
        rule["description"] = description
    references = entry.get("references")
    if (
        urls := [url for url in references if text_or_none(url)]
        if isinstance(references, list)
        else []
    ):
        rule["reference"] = urls
    return rule


def _candidate(entry: Mapping[str, Any], index: int, facts: _ReportFacts) -> _Candidate | None:
    name = text_or_none(entry.get("name"))
    if name is None:
        return None
    referenced = _referenced_calls(entry.get("data"), facts.calls)
    earliest = min(
        referenced, key=lambda c: (c.timestamp, c.call_id, c.process.pid, c.index), default=None
    )
    timestamp = earliest.timestamp if earliest else facts.fallback_time
    lane = call_lane(earliest) if earliest else "process"
    rule = _rule(entry, name)
    sections: dict[str, Any] = {"rule": rule}
    if technique_ids := facts.techniques.get(name):
        sections["threat"] = {"technique": {"id": technique_ids}}
    if referenced:
        event_ids = (api_event_id(facts.analysis_id, call) for call in referenced)
        sections["related"] = related_events(*event_ids)
    return _Candidate(
        SourceRecord(index, timestamp, entry),
        _shape(lane),
        rule.get("description", name),
        severity_level(entry.get("severity")),
        sections,
        _match_text(entry.get("data")),
    )
