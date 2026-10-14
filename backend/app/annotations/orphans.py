"""Finding annotations whose event or process is no longer in the analysis's index."""

import asyncio
from collections.abc import Iterable
from typing import Protocol

from app.annotations.validation import Target
from app.db.models.annotation import TargetType
from app.events.execution import run_search
from app.search.index import EventIndex

PRESENT = "present"


class HasTarget(Protocol):
    @property
    def target_type(self) -> TargetType: ...

    @property
    def target_ref(self) -> str: ...


async def orphaned_targets(
    index: EventIndex, analysis_id: int, annotations: Iterable[HasTarget]
) -> set[Target]:
    """The event and process targets among `annotations` that the index no longer has.

    One search per kind that occurs; analysis targets are never looked up.
    """
    wanted = {
        kind: {a.target_ref for a in annotations if a.target_type is kind}
        for kind in (TargetType.EVENT, TargetType.PROCESS)
    }
    events, processes = await asyncio.gather(
        _missing_events(index, analysis_id, wanted[TargetType.EVENT]),
        _missing_processes(index, analysis_id, wanted[TargetType.PROCESS]),
    )
    return {Target(TargetType.EVENT, ref) for ref in events} | {
        Target(TargetType.PROCESS, ref) for ref in processes
    }


async def _missing_events(index: EventIndex, analysis_id: int, refs: set[str]) -> set[str]:
    if not refs:
        return set()
    response = await run_search(
        index,
        analysis_id,
        {"size": len(refs), "query": {"ids": {"values": sorted(refs)}}, "_source": False},
    )
    return refs - {str(hit["_id"]) for hit in response["hits"]["hits"]}


async def _missing_processes(index: EventIndex, analysis_id: int, refs: set[str]) -> set[str]:
    if not refs:
        return set()
    pids = sorted(int(ref) for ref in refs)
    # The process view lists a process once it has an `entity_id`; a pid counts only then.
    body = {
        "size": 0,
        "query": {
            "bool": {
                "filter": [
                    {"exists": {"field": "process.entity_id"}},
                    {"terms": {"process.pid": pids}},
                ]
            }
        },
        "aggs": {PRESENT: {"terms": {"field": "process.pid", "size": len(pids)}}},
    }
    response = await run_search(index, analysis_id, body)
    present = {str(bucket["key"]) for bucket in response["aggregations"][PRESENT]["buckets"]}
    return refs - present
