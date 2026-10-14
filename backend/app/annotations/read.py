"""The read models of annotations: what the annotation endpoints and the detail views return."""

from collections.abc import Iterable, Iterator, Mapping, Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from app.annotations.orphans import orphaned_targets
from app.annotations.validation import Target
from app.db import annotation_repository as repository
from app.db.models import Note
from app.db.models.annotation import TargetType
from app.schemas.annotations import Annotations, NoteAnnotation, TagAnnotation
from app.schemas.views_events import ProcessNode, ProcessSummary
from app.search.index import EventIndex


def tag_annotation(
    assignment: repository.TagAssignment, *, orphaned: bool = False
) -> TagAnnotation:
    return TagAnnotation(
        link_id=assignment.link_id,
        tag=assignment.tag,
        target_type=assignment.target_type,
        target_ref=assignment.target_ref,
        orphaned=orphaned,
    )


def note_annotation(note: Note, *, orphaned: bool = False) -> NoteAnnotation:
    return NoteAnnotation(
        id=note.id,
        target_type=note.target_type,
        target_ref=note.target_ref,
        body=note.body,
        created_at=note.created_at,
        updated_at=note.updated_at,
        orphaned=orphaned,
    )


async def load_annotations(
    session: AsyncSession,
    index: EventIndex,
    analysis_id: int,
    *,
    target_type: TargetType | None = None,
    target_ref: str | None = None,
) -> Annotations:
    """Tags and notes of the analysis, or of one kind of target or one target, each marked
    orphaned when its event or process is gone from the index.
    """
    tags = await repository.tag_assignments(
        session, analysis_id, target_type=target_type, target_ref=target_ref
    )
    notes = await repository.notes_of(
        session, analysis_id, target_type=target_type, target_ref=target_ref
    )
    gone = await orphaned_targets(index, analysis_id, [*tags, *notes])
    return Annotations(
        tags=[
            tag_annotation(t, orphaned=Target(t.target_type, t.target_ref) in gone) for t in tags
        ],
        notes=[
            note_annotation(n, orphaned=Target(n.target_type, n.target_ref) in gone) for n in notes
        ],
    )


async def load_event_annotations(
    session: AsyncSession, analysis_id: int, event_id: str
) -> Annotations:
    """The annotations of an event that exists, so none is orphaned."""
    tags = await repository.tag_assignments(
        session, analysis_id, target_type=TargetType.EVENT, target_ref=event_id
    )
    notes = await repository.notes_of(
        session, analysis_id, target_type=TargetType.EVENT, target_ref=event_id
    )
    return Annotations(
        tags=[tag_annotation(t) for t in tags], notes=[note_annotation(n) for n in notes]
    )


def _walk(nodes: Sequence[ProcessNode]) -> Iterator[ProcessNode]:
    for node in nodes:
        yield node
        yield from _walk(node.children)


def mark_processes(
    processes: Iterable[ProcessSummary], marks: Mapping[str, repository.ProcessMarks]
) -> None:
    """Sets `tags` and `note_count` on each process from the annotations of its pid."""
    for process in processes:
        found = marks.get(str(process.pid))
        if found is not None:
            process.tags = found.tags
            process.note_count = found.note_count


async def mark_process_tree(
    session: AsyncSession, analysis_id: int, roots: Sequence[ProcessNode]
) -> None:
    mark_processes(_walk(roots), await repository.process_marks(session, analysis_id))
