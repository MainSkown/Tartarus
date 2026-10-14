"""The extra fields a search returns per event, beyond the typed ones."""

from app.errors import ApiError
from app.events.aggregatable import resolve_single_field
from app.search.fields import FieldType

INVALID_COLUMN = "invalid_column"
SHOWABLE = frozenset(FieldType) - {FieldType.OBJECT_DISABLED}


def resolve_columns(names: list[str]) -> list[str]:
    """The canonical field name of each column, in order and without repeats, or a 422
    `invalid_column` naming the first that cannot be shown."""
    resolved = [_canonical_name(name) for name in names]
    return list(dict.fromkeys(resolved))


def _canonical_name(name: str) -> str:
    target = resolve_single_field(name, SHOWABLE, INVALID_COLUMN)
    if target.path != target.definition.name:
        raise ApiError(
            422, INVALID_COLUMN, f"{name} is one argument; ask for {target.definition.name}"
        )
    return target.path
