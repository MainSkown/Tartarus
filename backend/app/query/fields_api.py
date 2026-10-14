"""The field catalog as the autocomplete endpoints present it."""

from dataclasses import dataclass

from app.search.fields import (
    COMPOSITE_ALIASES,
    FIELDS,
    FieldDefinition,
    FieldType,
    Lane,
    field_by_name,
)


@dataclass(frozen=True, slots=True)
class FieldInfo:
    """A field or composite alias the query bar can offer; `members` is set for a composite."""

    name: str
    type: FieldType
    aliases: tuple[str, ...]
    description: str
    example: str
    lane: Lane | None
    members: tuple[str, ...]
    searchable: bool


def _plain(field: FieldDefinition) -> FieldInfo:
    return FieldInfo(
        name=field.name,
        type=field.type,
        aliases=field.aliases,
        description=field.description,
        example=field.example,
        lane=field.lane,
        members=(),
        searchable=field.type is not FieldType.OBJECT_DISABLED,
    )


def _composite(alias: str, member_names: tuple[str, ...]) -> FieldInfo:
    first = field_by_name(member_names[0])
    return FieldInfo(
        name=alias,
        type=first.type,
        aliases=(),
        description=" or ".join(member_names),
        example=first.example,
        lane=first.lane,
        members=member_names,
        searchable=True,
    )


def field_catalog() -> list[FieldInfo]:
    return [
        *(_plain(field) for field in FIELDS),
        *(_composite(alias, members) for alias, members in COMPOSITE_ALIASES.items()),
    ]


def suggest_fields(prefix: str, limit: int = 20) -> list[FieldInfo]:
    """Searchable fields for the typed text: by name prefix, by alias prefix, then inside a name."""
    needle = prefix.lower()
    candidates = [entry for entry in field_catalog() if entry.searchable]
    tiers: list[list[FieldInfo]] = [[], [], []]
    for entry in candidates:
        if entry.name.lower().startswith(needle):
            tiers[0].append(entry)
        elif any(alias.startswith(needle) for alias in entry.aliases):
            tiers[1].append(entry)
        elif needle in entry.name.lower():
            tiers[2].append(entry)
    return [entry for tier in tiers for entry in tier][:limit]
