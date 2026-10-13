import asyncio
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any

from app.ingest.ecs import LANES, base_name
from app.schemas.views_events import (
    ApiCount,
    LoadedModule,
    ProcessDetail,
    ProcessEventRow,
    ProcessNode,
    ProcessSummary,
    ProcessTree,
)
from app.search.index import EventIndex
from app.views.event_fields import (
    TIME_ORDER,
    WITHOUT_RAW,
    Source,
    dig,
    event_id,
    event_time,
    hits_of,
    int_at,
    parse_time,
    severity_name,
    text_at,
    total_of,
)

MAX_PROCESSES = 1000
MAX_ALERTS = 1000
MAX_LINKED_EVENTS = 10_000
MAX_MODULES = 2000
HOSTS_PER_PROCESS = 50
INJECTIONS_PER_PROCESS = 50
TOP_API_COUNT = 15
EVENT_ROW_LIMIT = 200
DETAIL_LANES = ("process", "file", "registry", "network")
TERMINATED = "process-terminated"
INJECT_PREFIX = "inject-"
EPOCH = datetime.min.replace(tzinfo=UTC)


@dataclass(frozen=True)
class DetectionStats:
    count: int
    max_severity: int


@dataclass(frozen=True)
class _Load:
    name: str
    path: str | None
    base_address: str | None
    loaded_at: datetime
    explicit: bool


def _entity(entity_id: str) -> dict[str, Any]:
    return {"term": {"process.entity_id": entity_id}}


def _process_aggregations() -> dict[str, Any]:
    return {
        "by_process": {
            "terms": {"field": "process.entity_id", "size": MAX_PROCESSES},
            "aggs": {
                "record": {
                    "top_hits": {
                        "size": 1,
                        "sort": TIME_ORDER,
                        "_source": {"includes": ["process"]},
                    }
                },
                "ended": {
                    "filter": {"term": {"event.action": TERMINATED}},
                    "aggs": {"at": {"max": {"field": "@timestamp"}}},
                },
                "lanes": {"terms": {"field": "tartarus.lane", "size": len(LANES)}},
                "injected": {
                    "filter": {"prefix": {"event.action": INJECT_PREFIX}},
                    "aggs": {
                        "targets": {
                            "terms": {
                                "field": "tartarus.inject.target_pid",
                                "size": INJECTIONS_PER_PROCESS,
                            }
                        }
                    },
                },
                "network": {
                    "filter": {"term": {"tartarus.lane": "network"}},
                    "aggs": {
                        field: {"terms": {"field": field, "size": HOSTS_PER_PROCESS}}
                        for field in ("dns.question.name", "destination.domain", "destination.ip")
                    },
                },
            },
        }
    }


def attribute_alerts(
    alerts: Iterable[Source], entity_of_event: Mapping[str, str]
) -> dict[str, DetectionStats]:
    """Alerts carry no process of their own, so each belongs to the processes that made the
    calls it references (and to its own process when a source does set one).
    """
    stats: dict[str, DetectionStats] = {}
    for alert in alerts:
        severity = int_at(alert, "event", "severity") or 0
        owners = {
            entity_of_event[reference]
            for reference in _references(alert)
            if reference in entity_of_event
        }
        if own := text_at(alert, "process", "entity_id"):
            owners.add(own)
        for owner in owners:
            known = stats.get(owner)
            stats[owner] = DetectionStats(
                (known.count if known else 0) + 1,
                max(known.max_severity, severity) if known else severity,
            )
    return stats


def _references(alert: Source) -> list[str]:
    references = dig(alert, "related", "events")
    return [r for r in references if isinstance(r, str)] if isinstance(references, list) else []


async def _detection_stats(index: EventIndex, analysis_id: int) -> dict[str, DetectionStats]:
    alerts = hits_of(
        await index.search(
            analysis_id,
            {
                "size": MAX_ALERTS,
                "query": {"term": {"event.kind": "alert"}},
                "_source": ["event.severity", "related.events", "process.entity_id"],
            },
        )
    )
    referenced = list(dict.fromkeys(r for alert in alerts for r in _references(alert)))
    if not referenced:
        return attribute_alerts(alerts, {})
    calls = hits_of(
        await index.search(
            analysis_id,
            {
                "size": min(len(referenced), MAX_LINKED_EVENTS),
                "query": {"terms": {"event.id": referenced[:MAX_LINKED_EVENTS]}},
                "_source": ["event.id", "process.entity_id"],
            },
        )
    )
    entity_of_event = {
        event_id(call): entity
        for call in calls
        if (entity := text_at(call, "process", "entity_id"))
    }
    return attribute_alerts(alerts, entity_of_event)


def _bucket_keys(bucket: Mapping[str, Any]) -> list[str]:
    return [str(entry["key"]) for entry in bucket["buckets"]]


def _summary(bucket: Mapping[str, Any], detections: Mapping[str, DetectionStats]) -> ProcessSummary:
    record: Source = bucket["record"]["hits"]["hits"][0]["_source"].get("process", {})
    # The bucket key is lowercased by the field's normaliser; the document keeps its spelling.
    entity_id = text_at(record, "entity_id") or str(bucket["key"])
    stats = detections.get(entity_id)
    network = bucket["network"]
    ended = bucket["ended"]["at"].get("value_as_string")
    return ProcessSummary(
        entity_id=entity_id,
        pid=int_at(record, "pid") or 0,
        ppid=int_at(record, "parent", "pid"),
        name=text_at(record, "name"),
        executable=text_at(record, "executable"),
        command_line=text_at(record, "command_line"),
        start=parse_time(text_at(record, "start")),
        end=parse_time(ended),
        integrity=text_at(record, "integrity_level"),
        max_severity=severity_name(stats.max_severity) if stats else None,
        detection_count=stats.count if stats else 0,
        injected_into=[int(key) for key in _bucket_keys(bucket["injected"]["targets"])],
        network_hosts=list(
            dict.fromkeys(
                host
                for field in ("dns.question.name", "destination.domain", "destination.ip")
                for host in _bucket_keys(network[field])
            )
        ),
        event_counts_by_lane={
            str(entry["key"]): int(entry["doc_count"]) for entry in bucket["lanes"]["buckets"]
        },
    )


async def load_processes(index: EventIndex, analysis_id: int) -> list[ProcessSummary]:
    """Every process of the analysis, oldest first."""
    response, detections = await asyncio.gather(
        index.search(
            analysis_id,
            {
                "size": 0,
                "query": {"exists": {"field": "process.entity_id"}},
                "aggs": _process_aggregations(),
            },
        ),
        _detection_stats(index, analysis_id),
    )
    buckets = response.get("aggregations", {}).get("by_process", {}).get("buckets", [])
    return sorted(
        (_summary(bucket, detections) for bucket in buckets), key=lambda p: (_started(p), p.pid)
    )


def _started(process: ProcessSummary) -> datetime:
    return process.start or EPOCH


def build_tree(summaries: Sequence[ProcessSummary]) -> list[ProcessNode]:
    """Nests each process under the latest same-pid process that started before it.

    "Before" is the order of `(start, pid)`, which also rules out cycles.
    """
    ordered = sorted(summaries, key=lambda p: (_started(p), p.pid))
    nodes = [ProcessNode(**p.model_dump(), children=[]) for p in ordered]
    roots: list[ProcessNode] = []
    by_pid: dict[int, list[ProcessNode]] = defaultdict(list)
    for node in nodes:
        parents = by_pid.get(node.ppid) if node.ppid is not None else None
        (parents[-1].children if parents else roots).append(node)
        by_pid[node.pid].append(node)
    return roots


async def process_tree(index: EventIndex, analysis_id: int) -> ProcessTree:
    summaries = await load_processes(index, analysis_id)
    return ProcessTree(roots=build_tree(summaries), total=len(summaries))


_LOAD_CALLS = {
    "ldrloaddll": ("FileName", "BaseAddress"),
    "dllloadnotification": ("DllName", "DllBase"),
}


def _read_load(event: Source) -> _Load | None:
    api = text_at(event, "api", "name")
    arguments = dig(event, "api", "arguments")
    if api is None or api.casefold() not in _LOAD_CALLS or not isinstance(arguments, Mapping):
        return None
    if api.casefold() == "dllloadnotification" and arguments.get("NotificationReason") != "load":
        return None
    name_argument, address_argument = _LOAD_CALLS[api.casefold()]
    value = arguments.get(name_argument)
    if not isinstance(value, str) or not value:
        return None
    address = arguments.get(address_argument)
    return _Load(
        name=base_name(value),
        path=value if "\\" in value or "/" in value else None,
        base_address=address if isinstance(address, str) and address else None,
        loaded_at=event_time(event),
        explicit=api.casefold() == "ldrloaddll",
    )


def loaded_modules(events: Iterable[Source]) -> list[LoadedModule]:
    """Distinct libraries from `LdrLoadDll` and the loader's load notifications.

    One base address is one module. The explicit `LdrLoadDll` call names it better (the
    notification drops the extension), so it wins; the first load time is kept either way.
    """
    seen: dict[str, _Load] = {}
    for event in events:
        load = _read_load(event)
        if load is None:
            continue
        key = load.base_address or load.name.casefold()
        known = seen.get(key)
        if known is None:
            seen[key] = load
        elif load.explicit and not known.explicit:
            seen[key] = replace(load, loaded_at=min(known.loaded_at, load.loaded_at))
    return [
        LoadedModule(
            name=load.name,
            path=load.path,
            base_address=load.base_address,
            loaded_at=load.loaded_at,
        )
        for load in seen.values()
    ]


def _event_row(source: Source) -> ProcessEventRow:
    return ProcessEventRow(
        time=event_time(source),
        action=text_at(source, "event", "action") or "",
        summary=text_at(source, "tartarus", "summary") or "",
        lane=text_at(source, "tartarus", "lane") or "",
        event_id=event_id(source),
    )


async def _modules_of(index: EventIndex, analysis_id: int, entity_id: str) -> list[LoadedModule]:
    response = await index.search(
        analysis_id,
        {
            "size": MAX_MODULES,
            "query": {
                "bool": {"filter": [_entity(entity_id), {"terms": {"api.name": list(_LOAD_CALLS)}}]}
            },
            "sort": TIME_ORDER,
            "_source": ["@timestamp", "api"],
        },
    )
    return loaded_modules(hits_of(response))


async def _top_apis_of(index: EventIndex, analysis_id: int, entity_id: str) -> list[ApiCount]:
    response = await index.search(
        analysis_id,
        {
            "size": 0,
            "query": _entity(entity_id),
            "aggs": {
                "apis": {
                    "terms": {"field": "api.name", "size": TOP_API_COUNT},
                    # The field's normaliser lowercases the key; the call keeps its spelling.
                    "aggs": {"spelling": {"top_hits": {"size": 1, "_source": ["api.name"]}}},
                }
            },
        },
    )
    buckets = response.get("aggregations", {}).get("apis", {}).get("buckets", [])
    return [
        ApiCount(
            name=text_at(bucket["spelling"]["hits"]["hits"][0]["_source"], "api", "name")
            or str(bucket["key"]),
            count=int(bucket["doc_count"]),
        )
        for bucket in buckets
    ]


async def _events_of(
    index: EventIndex, analysis_id: int, entity_id: str
) -> tuple[list[ProcessEventRow], int]:
    response = await index.search(
        analysis_id,
        {
            "size": EVENT_ROW_LIMIT,
            "track_total_hits": True,
            "query": {
                "bool": {"filter": [_entity(entity_id), {"terms": {"tartarus.lane": DETAIL_LANES}}]}
            },
            "sort": [{"@timestamp": "desc"}, {"event.sequence": "desc"}],
            "_source": WITHOUT_RAW,
        },
    )
    return [_event_row(source) for source in hits_of(response)], total_of(response)


async def process_detail(index: EventIndex, analysis_id: int, pid: int) -> ProcessDetail | None:
    """The first process with this pid (a reused pid has several), or None if there is none."""
    summary = next((p for p in await load_processes(index, analysis_id) if p.pid == pid), None)
    if summary is None:
        return None
    modules, top_apis, (events, event_total) = await asyncio.gather(
        _modules_of(index, analysis_id, summary.entity_id),
        _top_apis_of(index, analysis_id, summary.entity_id),
        _events_of(index, analysis_id, summary.entity_id),
    )
    return ProcessDetail(
        **summary.model_dump(),
        modules=modules,
        top_apis=top_apis,
        events=events,
        event_total=event_total,
    )
