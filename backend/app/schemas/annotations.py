from datetime import datetime
from typing import Annotated, Self

from pydantic import (
    AfterValidator,
    ConfigDict,
    Field,
    ValidationInfo,
    field_validator,
    model_validator,
)

from app.annotations.validation import (
    MAX_NOTE_LENGTH,
    MAX_TAG_NAME_LENGTH,
    canonical_target_ref,
    checked_note_body,
    normalise_tag_name,
)
from app.db.models.annotation import TargetType
from app.schemas.base import ApiModel

type TagName = Annotated[
    str,
    Field(
        max_length=MAX_TAG_NAME_LENGTH,
        description="Lower-cased; 1 to 40 characters of a-z, 0-9, '.', '_' and '-'.",
    ),
    AfterValidator(normalise_tag_name),
]
type NoteBody = Annotated[
    str,
    Field(max_length=MAX_NOTE_LENGTH, description="Plain text, 1 to 20 000 characters."),
    AfterValidator(checked_note_body),
]

TARGET_REF_DESCRIPTION = (
    "What the target is: empty for the analysis, the pid for a process, the `event.id` for an "
    "event."
)


class AnnotationTarget(ApiModel):
    target_type: TargetType
    target_ref: str = Field(default="", validate_default=True, description=TARGET_REF_DESCRIPTION)

    @field_validator("target_ref")
    @classmethod
    def _canonical_ref(cls, ref: str, info: ValidationInfo) -> str:
        target_type = info.data.get("target_type")
        return ref if target_type is None else canonical_target_ref(target_type, ref)


class TagCreate(AnnotationTarget):
    tag: TagName


class NoteCreate(AnnotationTarget):
    body: NoteBody


class NoteUpdate(ApiModel):
    body: NoteBody


class AnnotationFilter(ApiModel):
    """Narrows the annotations to one kind of target, or to one target of that kind."""

    model_config = ConfigDict(extra="forbid")

    target_type: TargetType | None = None
    target_ref: str | None = Field(default=None, description=TARGET_REF_DESCRIPTION)

    @model_validator(mode="after")
    def _ref_needs_a_type(self) -> Self:
        if self.target_ref is None:
            return self
        if self.target_type is None:
            raise ValueError("target_ref needs a target_type")
        self.target_ref = canonical_target_ref(self.target_type, self.target_ref)
        return self


class TagUsageRead(ApiModel):
    name: str
    count: int = Field(description="Links using the tag across all analyses.")


class TagAnnotation(ApiModel):
    link_id: int
    tag: str
    target_type: TargetType
    target_ref: str
    orphaned: bool = Field(
        description="True when the event or process the tag is on is no longer in the analysis. "
        "Only the annotations listing checks; the answers to a write say false."
    )


class NoteAnnotation(ApiModel):
    id: int
    target_type: TargetType
    target_ref: str
    body: str
    created_at: datetime
    updated_at: datetime
    orphaned: bool = Field(
        description="True when the event or process the note is on is no longer in the analysis. "
        "Only the annotations listing checks; the answers to a write say false."
    )


class Annotations(ApiModel):
    tags: list[TagAnnotation] = Field(default_factory=list)
    notes: list[NoteAnnotation] = Field(default_factory=list)
