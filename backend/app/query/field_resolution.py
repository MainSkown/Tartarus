"""Query field names to catalog fields: the one place a typed name becomes something queryable."""

from dataclasses import dataclass
from difflib import SequenceMatcher

from app.search.fields import (
    COMPOSITE_ALIASES,
    FIELDS,
    FieldDefinition,
    FieldType,
    resolve_composite,
    resolve_field,
)

SUGGESTION_CUTOFF = 0.6
SUGGESTION_MARGIN = 0.1
MAX_SUGGESTIONS = 3

_FLAT_OBJECTS = tuple(field for field in FIELDS if field.type is FieldType.FLAT_OBJECT)
_KNOWN_NAMES = tuple(
    sorted(
        {field.name for field in FIELDS}
        | {alias for field in FIELDS for alias in field.aliases}
        | set(COMPOSITE_ALIASES)
    )
)


@dataclass(frozen=True, slots=True)
class Target:
    """One index field a query field name reaches; `path` differs from the definition's name
    only for an argument inside a flat object, such as `api.arguments.FileName`."""

    path: str
    definition: FieldDefinition


@dataclass(frozen=True, slots=True)
class ResolvedField:
    label: str
    targets: tuple[Target, ...]


def resolve_query_field(name: str) -> ResolvedField | None:
    """Resolves a name or alias, in any letter case, to the fields it stands for.

    A name below a flat-object field (`api.arguments.FileName`) is accepted for any argument
    name, since the arguments are not in the catalog; the argument name keeps its case.
    """
    key = name.lower()
    if members := resolve_composite(key):
        return ResolvedField(key, tuple(Target(m.name, m) for m in members))
    if (definition := resolve_field(key)) is not None:
        return ResolvedField(definition.name, (Target(definition.name, definition),))
    return _flat_object_argument(name)


def _flat_object_argument(name: str) -> ResolvedField | None:
    for definition in _FLAT_OBJECTS:
        prefix = f"{definition.name}."
        if name.lower().startswith(prefix) and len(name) > len(prefix):
            path = prefix + name[len(prefix) :]
            return ResolvedField(path, (Target(path, definition),))
    return None


def similar_field_names(name: str) -> list[str]:
    """Names and aliases close to `name`, best first: only those about as close as the best."""
    key = name.lower()
    scored = sorted(
        ((SequenceMatcher(None, key, known).ratio(), known) for known in _KNOWN_NAMES),
        key=lambda pair: (-pair[0], pair[1]),
    )
    if not scored or scored[0][0] < SUGGESTION_CUTOFF:
        return []
    best = scored[0][0]
    close = [known for ratio, known in scored if ratio >= best - SUGGESTION_MARGIN]
    return close[:MAX_SUGGESTIONS]
