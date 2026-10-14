from collections.abc import Callable, Mapping
from typing import Any

type Event = Mapping[str, Any]
type Predicate = Callable[[Event], bool]


def values_at(event: Event, path: tuple[str, ...]) -> list[Any]:
    """Every value under the dotted `path` of a nested event document; empty if there is none.

    A list on the way (`registry.data.strings`, `dns.answers`) is flattened, so a path matches
    when any element has it, as an OpenSearch query on the same document would.
    """
    node: Any = event
    for position, key in enumerate(path):
        # `dict` is tested before `Mapping`: the ABC check costs more than the rest of the
        # lookup, and documents are plain dicts nearly always.
        if type(node) is dict:
            if key not in node:
                return []
            node = node[key]
        else:
            return _values_through_lists(node, path[position:])
    return node if type(node) is list else [node]


def _values_through_lists(node: Any, path: tuple[str, ...]) -> list[Any]:
    nodes: list[Any] = node if isinstance(node, list) else [node]
    for key in path:
        found: list[Any] = []
        for candidate in nodes:
            if isinstance(candidate, Mapping) and key in candidate:
                child = candidate[key]
                found.extend(child) if isinstance(child, list) else found.append(child)
        if not found:
            return []
        nodes = found
    return nodes
