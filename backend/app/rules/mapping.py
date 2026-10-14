from collections.abc import Iterator, Mapping
from functools import cache

from sigma.processing.conditions import IncludeFieldCondition
from sigma.processing.pipeline import ProcessingItem, ProcessingPipeline
from sigma.processing.transformations import FieldMappingTransformation, MapStringTransformation
from sigma.rule import SigmaRule
from sigma.rule.detection import SigmaDetection, SigmaDetectionItem

from app.rules.rule import invalid
from app.search.fields import field_by_name

EVENT_ACTION = "event.action"

_PROCESS = {
    "Image": "process.executable",
    "CommandLine": "process.command_line",
    "ParentImage": "process.parent.executable",
    "ParentCommandLine": "process.parent.command_line",
    "ProcessId": "process.pid",
    "ParentProcessId": "process.parent.pid",
}
_REGISTRY = {
    **_PROCESS,
    "TargetObject": "registry.path",
    "Details": "registry.data.strings",
    "EventType": EVENT_ACTION,
}
_NETWORK = {
    **_PROCESS,
    "DestinationIp": "destination.ip",
    "DestinationPort": "destination.port",
    "DestinationHostname": "destination.domain",
    "SourceIp": "source.ip",
    "SourcePort": "source.port",
}

# One table per logsource category: a Sigma name can mean different things in different
# categories, and a name a category does not list is not mapped there (no fallback field).
FIELD_MAPS: dict[str, Mapping[str, str]] = {
    "process_creation": _PROCESS,
    "file_event": {**_PROCESS, "TargetFilename": "file.path"},
    "registry_set": _REGISTRY,
    "registry_add": _REGISTRY,
    "registry_delete": _REGISTRY,
    "network_connection": _NETWORK,
    "dns_query": {**_PROCESS, "QueryName": "dns.question.name", "QueryResults": "dns.answers.data"},
    "create_remote_thread": {
        "SourceImage": "process.executable",
        "SourceProcessId": "process.pid",
        "TargetImage": "tartarus.inject.target_executable",
        "TargetProcessId": "tartarus.inject.target_pid",
    },
}

# Sysmon names the registry operation in `EventType`; our events carry it in `event.action`.
EVENT_TYPE_ACTIONS = {
    "SetValue": "reg-value-set",
    "CreateKey": "reg-key-created",
    "DeleteValue": "reg-value-deleted",
    "DeleteKey": "reg-key-deleted",
}


@cache
def _pipeline(category: str) -> ProcessingPipeline:
    table = FIELD_MAPS[category]
    renames: dict[str | None, str | list[str]] = {}
    renames.update((name, target) for name, target in table.items())
    items = [
        ProcessingItem(
            identifier=f"{category}-fields", transformation=FieldMappingTransformation(renames)
        )
    ]
    if EVENT_ACTION in table.values():
        items.append(
            ProcessingItem(
                identifier=f"{category}-event-type",
                transformation=MapStringTransformation(dict(EVENT_TYPE_ACTIONS)),
                field_name_conditions=[IncludeFieldCondition([EVENT_ACTION])],
            )
        )
    return ProcessingPipeline(name=f"tartarus-{category}", items=items)


def map_fields(rule: SigmaRule, category: str) -> None:
    """Renames the rule's Sigma fields to catalog fields, in place.

    Raises an `INVALID` `RuleProblem` naming every field the category's table does not map and
    that is not already a catalog field (a custom rule may use ECS names directly).
    """
    _pipeline(category).apply(rule)
    unmapped = list(dict.fromkeys(f for f in _fields_of(rule) if not _in_catalog(f)))
    if unmapped:
        raise invalid(
            f"field {', '.join(unmapped)} is not mapped for logsource category {category}"
        )


def _fields_of(rule: SigmaRule) -> Iterator[str]:
    for detection in rule.detection.detections.values():
        yield from _fields_in(detection)


def _fields_in(detection: SigmaDetection) -> Iterator[str]:
    for item in detection.detection_items:
        if isinstance(item, SigmaDetection):
            yield from _fields_in(item)
        elif isinstance(item, SigmaDetectionItem) and item.field is not None:
            yield item.field


def _in_catalog(name: str) -> bool:
    try:
        field_by_name(name)
    except KeyError:
        return False
    return True
