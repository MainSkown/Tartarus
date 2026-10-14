from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.annotations.read import load_annotations, note_annotation, tag_annotation
from app.annotations.validation import Target
from app.api.dependencies import get_event_index, require_analysis
from app.db import annotation_repository as repository
from app.db.models.analysis import AnalysisStatus
from app.db.models.annotation import TargetType
from app.db.session import get_session
from app.schemas.annotations import (
    AnnotationFilter,
    Annotations,
    NoteAnnotation,
    NoteCreate,
    NoteUpdate,
    TagAnnotation,
    TagCreate,
    TagUsageRead,
)
from app.search.index import EventIndex

router = APIRouter(tags=["annotations"])

Session = Annotated[AsyncSession, Depends(get_session)]
Events = Annotated[EventIndex, Depends(get_event_index)]


async def _require_annotatable(session: AsyncSession, analysis_id: int, target: Target) -> None:
    analysis = await require_analysis(session, analysis_id)
    if target.type is TargetType.EVENT and analysis.status is not AnalysisStatus.DONE:
        raise HTTPException(
            409,
            f"Analysis {analysis_id} is {analysis.status.value}: "
            "events can be annotated once the analysis is finished",
        )


@router.get("/tags", name="list_tags")
async def list_tags(session: Session) -> list[TagUsageRead]:
    """Every tag in use with the number of links using it across all analyses, most used first,
    then by name. Feeds tag autocomplete.
    """
    return [TagUsageRead(name=u.name, count=u.count) for u in await repository.tag_usage(session)]


@router.get("/analyses/{analysis_id}/annotations", name="read")
async def read(
    analysis_id: int,
    session: Session,
    events: Events,
    narrowed_to: Annotated[AnnotationFilter, Query()],
) -> Annotations:
    """The analysis's tags and notes, oldest first. `target_type` narrows them to the analysis,
    its processes or its events, and `target_ref` (the pid or the event id; needs `target_type`)
    to one target. An event or process annotation whose target is gone from the analysis comes
    with `orphaned: true`; it is kept, never deleted.
    """
    await require_analysis(session, analysis_id)
    return await load_annotations(
        session,
        events,
        analysis_id,
        target_type=narrowed_to.target_type,
        target_ref=narrowed_to.target_ref,
    )


@router.post("/analyses/{analysis_id}/tags", name="add_tag", status_code=201)
async def add_tag(analysis_id: int, body: TagCreate, session: Session) -> TagAnnotation:
    """Puts a tag on the analysis, a process (`target_ref` is the pid) or an event (`target_ref`
    is the event id), creating the tag if it is new. Names are lower-cased. `409` when the tag
    is already on that target, and for an event unless the analysis is `done`.
    """
    target = Target(body.target_type, body.target_ref)
    await _require_annotatable(session, analysis_id, target)
    try:
        added = await repository.add_tag(session, analysis_id, target, body.tag)
    except repository.TagLinkExistsError:
        raise HTTPException(409, f"Tag {body.tag} is already on this target") from None
    return tag_annotation(added)


@router.delete("/analyses/{analysis_id}/tags/{link_id}", name="remove_tag", status_code=204)
async def remove_tag(analysis_id: int, link_id: int, session: Session) -> Response:
    """Takes a tag off its target. `404` for a link that is not this analysis's. A tag no link
    uses any more is deleted.
    """
    await require_analysis(session, analysis_id)
    if not await repository.remove_tag_link(session, analysis_id, link_id):
        raise HTTPException(404, f"Tag link {link_id} not found in analysis {analysis_id}")
    return Response(status_code=204)


@router.post("/analyses/{analysis_id}/notes", name="add_note", status_code=201)
async def add_note(analysis_id: int, body: NoteCreate, session: Session) -> NoteAnnotation:
    """Adds a plain-text note (1 to 20 000 characters) to the analysis, a process or an event.
    `409` for an event unless the analysis is `done`.
    """
    target = Target(body.target_type, body.target_ref)
    await _require_annotatable(session, analysis_id, target)
    return note_annotation(await repository.add_note(session, analysis_id, target, body.body))


@router.patch("/notes/{note_id}", name="update_note")
async def update_note(note_id: int, body: NoteUpdate, session: Session) -> NoteAnnotation:
    """Replaces a note's text."""
    updated = await repository.update_note(session, note_id, body.body)
    if updated is None:
        raise HTTPException(404, f"Note {note_id} not found")
    return note_annotation(updated)


@router.delete("/notes/{note_id}", name="delete_note", status_code=204)
async def delete_note(note_id: int, session: Session) -> Response:
    """Deletes a note."""
    if not await repository.delete_note(session, note_id):
        raise HTTPException(404, f"Note {note_id} not found")
    return Response(status_code=204)
