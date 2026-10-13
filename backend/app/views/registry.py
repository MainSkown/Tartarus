from collections.abc import Iterable

from app.schemas.views_events import RegistryChange, RegistryKeyGroup, RegistryView
from app.search.index import EventIndex
from app.views.event_fields import (
    TIME_ORDER,
    WITHOUT_RAW,
    Source,
    event_id,
    event_time,
    hits_of,
    process_ref,
    text_at,
    texts_at,
    total_of,
)

REGISTRY_EVENT_CAP = 10_000


def _change(event: Source) -> RegistryChange:
    return RegistryChange(
        event_id=event_id(event),
        time=event_time(event),
        action=text_at(event, "event", "action") or "",
        value_name=text_at(event, "registry", "value"),
        data_type=text_at(event, "registry", "data", "type"),
        data=texts_at(event, "registry", "data", "strings"),
        process=process_ref(event),
    )


def group_registry_changes(events: Iterable[Source]) -> list[RegistryKeyGroup]:
    """Groups changes by hive and key (keys are case-insensitive), ordered by first change."""
    groups: dict[tuple[str, str], RegistryKeyGroup] = {}
    for event in sorted(events, key=event_time):
        key = text_at(event, "registry", "key")
        if key is None:
            continue
        hive = text_at(event, "registry", "hive")
        group = groups.setdefault(
            ((hive or "").casefold(), key.casefold()),
            RegistryKeyGroup(key=key, hive=hive, changes=[]),
        )
        group.changes.append(_change(event))
    return list(groups.values())


async def registry_view(index: EventIndex, analysis_id: int) -> RegistryView:
    response = await index.search(
        analysis_id,
        {
            "size": REGISTRY_EVENT_CAP,
            "track_total_hits": True,
            "query": {
                "bool": {
                    "filter": [
                        {"term": {"tartarus.lane": "registry"}},
                        {"term": {"event.kind": "event"}},
                    ]
                }
            },
            "sort": TIME_ORDER,
            "_source": WITHOUT_RAW,
        },
    )
    return RegistryView(keys=group_registry_changes(hits_of(response)), total=total_of(response))
