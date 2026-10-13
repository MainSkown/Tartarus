from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from app.db.models import Analysis
from app.ingest.reading import section
from app.schemas.views_events import ProcessRef
from app.schemas.views_findings import Ioc, IocsView, IocType
from app.search.index import EventIndex
from app.views.artifacts import AnalysisFiles
from app.views.event_fields import TIME_ORDER, Source, dig, hits_of, process_ref, text_at

# The guest and its gateway; every flow touches them, so they say nothing about the sample.
SANDBOX_NETWORK = "192.168.150.0/24"
VALUES_PER_TYPE = 500
EVENTS_PER_IOC = 10
MUTEX_CONTEXT = "Mutex named in the behavior summary"
TYPE_ORDER = list(IocType)


@dataclass(frozen=True)
class _EventIoc:
    """An indicator that is one field of the events, optionally only in one lane."""

    type: IocType
    field: str
    lane: str | None = None
    not_in_network: str | None = None

    @property
    def query(self) -> dict[str, Any]:
        filters = [{"term": {"tartarus.lane": self.lane}}] if self.lane else []
        excluded = [{"term": {self.field: self.not_in_network}}] if self.not_in_network else []
        return {"bool": {"filter": filters, "must_not": excluded}}


EVENT_IOCS = (
    _EventIoc(IocType.DOMAIN, "dns.question.name"),
    _EventIoc(IocType.IP, "destination.ip", not_in_network=SANDBOX_NETWORK),
    _EventIoc(IocType.URL, "url.full"),
    _EventIoc(IocType.REGISTRY, "registry.path", lane="registry"),
    _EventIoc(IocType.FILE, "file.path", lane="file"),
)


async def collect_iocs(index: EventIndex, analysis: Analysis, files: AnalysisFiles) -> IocsView:
    found = await _event_iocs(index, analysis.id)
    iocs = [*found.iocs, *_report_iocs(analysis, files)]
    iocs.sort(key=lambda ioc: (TYPE_ORDER.index(ioc.type), -ioc.count, ioc.value.lower()))
    return IocsView(iocs=iocs, truncated_types=found.truncated_types)


@dataclass(frozen=True)
class _EventIocs:
    iocs: list[Ioc]
    truncated_types: list[IocType]


async def _event_iocs(index: EventIndex, analysis_id: int) -> _EventIocs:
    response = await index.search(
        analysis_id,
        {"size": 0, "aggs": {spec.type.value: _aggregation(spec) for spec in EVENT_IOCS}},
    )
    aggregations: Mapping[str, Any] = response.get("aggregations", {})
    iocs: list[Ioc] = []
    truncated: list[IocType] = []
    for spec in EVENT_IOCS:
        values = aggregations.get(spec.type.value, {}).get("values", {})
        iocs.extend(_ioc(spec, bucket) for bucket in values.get("buckets", []))
        if values.get("sum_other_doc_count"):
            truncated.append(spec.type)
    return _EventIocs(iocs, truncated)


def _aggregation(spec: _EventIoc) -> dict[str, Any]:
    first_events = {
        "size": EVENTS_PER_IOC,
        "sort": TIME_ORDER,
        "_source": {
            "includes": ["event.id", spec.field, "tartarus.summary", "process.pid", "process.name"]
        },
    }
    return {
        "filter": spec.query,
        "aggs": {
            "values": {
                "terms": {"field": spec.field, "size": VALUES_PER_TYPE},
                "aggs": {"events": {"top_hits": first_events}},
            }
        },
    }


def _ioc(spec: _EventIoc, bucket: Mapping[str, Any]) -> Ioc:
    events = hits_of(bucket["events"])
    # The index folds case, so the bucket key is lowercase; the first event has the original.
    original = text_at(events[0], *spec.field.split(".")) if events else None
    return Ioc(
        type=spec.type,
        value=original or str(bucket["key"]),
        count=int(bucket["doc_count"]),
        context=_context(events),
        source_event_ids=[str(dig(event, "event", "id")) for event in events],
        process=next((ref for event in events if (ref := process_ref(event))), None),
    )


def _context(events: list[Source]) -> str:
    return (text_at(events[0], "tartarus", "summary") if events else None) or ""


def _report_iocs(analysis: Analysis, files: AnalysisFiles) -> list[Ioc]:
    found: dict[tuple[IocType, str], Ioc] = {}
    candidates = [
        *_hash_iocs(analysis, files),
        *_mutex_iocs(files.report),
    ]
    for candidate in candidates:
        key = (candidate.type, candidate.value.lower())
        known = found.get(key)
        found[key] = (
            candidate if known is None else known.model_copy(update={"count": known.count + 1})
        )
    return list(found.values())


def _hash_iocs(analysis: Analysis, files: AnalysisFiles) -> Iterable[Ioc]:
    yield _report_ioc(IocType.HASH, analysis.sample_sha256, f"Submitted sample {analysis.filename}")
    view = files.catalog.view
    for label, artifacts in (("Dropped file", view.dropped), ("Payload", view.payloads)):
        for artifact in artifacts:
            if artifact.sha256:
                yield _report_ioc(
                    IocType.HASH,
                    artifact.sha256,
                    f"{label} {artifact.name}",
                    process=artifact.source_process,
                )


def _mutex_iocs(report: Mapping[str, Any] | None) -> Iterable[Ioc]:
    mutexes = section(section(report or {}, "behavior"), "summary").get("mutexes")
    for mutex in mutexes if isinstance(mutexes, list) else []:
        if isinstance(mutex, str) and mutex:
            yield _report_ioc(IocType.MUTEX, mutex, MUTEX_CONTEXT)


def _report_ioc(type_: IocType, value: str, context: str, process: ProcessRef | None = None) -> Ioc:
    return Ioc(
        type=type_, value=value, count=1, context=context, source_event_ids=[], process=process
    )
