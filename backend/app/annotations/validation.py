"""What a tag name, a note and an annotation target may be: the one definition the API schemas
and the repository both check against.
"""

import re
from dataclasses import dataclass

from app.db.models.annotation import TargetType

MAX_TAG_NAME_LENGTH = 40
MAX_NOTE_LENGTH = 20_000
MAX_PID_DIGITS = 10

_TAG_NAME = re.compile(rf"[a-z0-9._-]{{1,{MAX_TAG_NAME_LENGTH}}}")
_PID = re.compile(rf"[0-9]{{1,{MAX_PID_DIGITS}}}")


@dataclass(frozen=True, slots=True)
class Target:
    """What an annotation is about: the analysis (`ref` empty), a pid, or an `event.id`."""

    type: TargetType
    ref: str = ""


def normalise_tag_name(name: str) -> str:
    lowered = name.lower()
    if not _TAG_NAME.fullmatch(lowered):
        raise ValueError(
            f"A tag name is 1 to {MAX_TAG_NAME_LENGTH} characters of a-z, 0-9, '.', '_' and '-'"
        )
    return lowered


def checked_note_body(body: str) -> str:
    if not body.strip():
        raise ValueError("A note cannot be empty")
    if len(body) > MAX_NOTE_LENGTH:
        raise ValueError(f"A note is at most {MAX_NOTE_LENGTH} characters")
    return body


def canonical_target_ref(target_type: TargetType, ref: str) -> str:
    """The stored spelling of `ref`: `""` for the analysis, the pid without leading zeros for a
    process, the event id as given.
    """
    if target_type is TargetType.ANALYSIS:
        if ref:
            raise ValueError("The analysis has no target_ref")
        return ""
    if target_type is TargetType.PROCESS:
        if not _PID.fullmatch(ref):
            raise ValueError("A process target_ref is the pid, digits only")
        return str(int(ref))
    if not ref:
        raise ValueError("An event target_ref is the event id")
    return ref
