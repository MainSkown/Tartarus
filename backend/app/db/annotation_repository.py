from collections.abc import Collection
from dataclasses import dataclass

from sqlalchemy import ColumnElement, delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.annotations.validation import (
    Target,
    checked_note_body,
    normalise_tag_name,
)
from app.db.base import utc_now
from app.db.models import Note, Tag, TagLink
from app.db.models.annotation import TargetType


class TagLinkExistsError(Exception):
    """The tag is already on that target of that analysis."""


@dataclass(frozen=True, slots=True)
class TagAssignment:
    link_id: int
    tag: str
    target_type: TargetType
    target_ref: str


@dataclass(frozen=True, slots=True)
class TagUsage:
    name: str
    count: int


@dataclass(frozen=True, slots=True)
class AnalysisAnnotations:
    tags: list[TagAssignment]
    notes: list[Note]


def _on_target(
    model: type[TagLink] | type[Note], target_type: TargetType | None, target_ref: str | None
) -> list[ColumnElement[bool]]:
    criteria: list[ColumnElement[bool]] = []
    if target_type is not None:
        criteria.append(model.target_type == target_type)
    if target_ref is not None:
        criteria.append(model.target_ref == target_ref)
    return criteria


async def add_tag(
    session: AsyncSession, analysis_id: int, target: Target, name: str
) -> TagAssignment:
    """Puts the tag on the target, creating the tag if it is new.

    Raises `ValueError` for a name that is not a tag name and `TagLinkExistsError` when the tag is
    already on that target.
    """
    tag_name = normalise_tag_name(name)
    tag = await _get_or_create_tag(session, tag_name)
    link = TagLink(
        tag_id=tag.id, analysis_id=analysis_id, target_type=target.type, target_ref=target.ref
    )
    session.add(link)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        if await _link_exists(session, tag_name, analysis_id, target):
            raise TagLinkExistsError(tag_name) from None
        raise
    return TagAssignment(link.id, tag_name, target.type, target.ref)


async def _get_or_create_tag(session: AsyncSession, name: str) -> Tag:
    tag = await session.scalar(select(Tag).where(Tag.name == name))
    if tag is None:
        tag = Tag(name=name)
        session.add(tag)
        await session.flush()
    return tag


async def _link_exists(
    session: AsyncSession, tag_name: str, analysis_id: int, target: Target
) -> bool:
    statement = (
        select(TagLink.id)
        .join(Tag, Tag.id == TagLink.tag_id)
        .where(
            Tag.name == tag_name,
            TagLink.analysis_id == analysis_id,
            TagLink.target_type == target.type,
            TagLink.target_ref == target.ref,
        )
    )
    return await session.scalar(statement) is not None


async def remove_tag_link(session: AsyncSession, analysis_id: int, link_id: int) -> bool:
    """Takes the tag off that target, and drops the tag itself once no link uses it. False when
    the analysis has no such link.
    """
    link = await session.scalar(
        select(TagLink).where(TagLink.id == link_id, TagLink.analysis_id == analysis_id)
    )
    if link is None:
        return False
    await session.delete(link)
    await session.flush()
    await _delete_unused_tags(session)
    await session.commit()
    return True


async def delete_unused_tags(session: AsyncSession) -> None:
    """For callers that removed links without going through `remove_tag_link`, such as the
    cascade of a deleted analysis.
    """
    await _delete_unused_tags(session)
    await session.commit()


async def _delete_unused_tags(session: AsyncSession) -> None:
    in_use = select(TagLink.id).where(TagLink.tag_id == Tag.id).exists()
    await session.execute(delete(Tag).where(~in_use))


async def tag_usage(session: AsyncSession) -> list[TagUsage]:
    """Every tag in use with its number of links, most used first, then by name."""
    links = func.count(TagLink.id)
    statement = (
        select(Tag.name, links)
        .join(TagLink, TagLink.tag_id == Tag.id)
        .group_by(Tag.id)
        .order_by(links.desc(), Tag.name)
    )
    return [TagUsage(name, count) for name, count in await session.execute(statement)]


async def tag_assignments(
    session: AsyncSession,
    analysis_id: int,
    *,
    target_type: TargetType | None = None,
    target_ref: str | None = None,
) -> list[TagAssignment]:
    """The analysis's tags, in the order they were added; narrowed by the target if given."""
    statement = (
        select(TagLink.id, Tag.name, TagLink.target_type, TagLink.target_ref)
        .join(Tag, Tag.id == TagLink.tag_id)
        .where(TagLink.analysis_id == analysis_id, *_on_target(TagLink, target_type, target_ref))
        .order_by(TagLink.id)
    )
    return [TagAssignment(*row) for row in await session.execute(statement)]


async def analysis_level_tags(
    session: AsyncSession, analysis_ids: Collection[int]
) -> dict[int, list[str]]:
    """The tags on the analyses themselves, sorted by name; an analysis with none is absent."""
    if not analysis_ids:
        return {}
    statement = (
        select(TagLink.analysis_id, Tag.name)
        .join(Tag, Tag.id == TagLink.tag_id)
        .where(TagLink.analysis_id.in_(analysis_ids), TagLink.target_type == TargetType.ANALYSIS)
        .order_by(Tag.name)
    )
    tags: dict[int, list[str]] = {}
    for analysis_id, name in await session.execute(statement):
        tags.setdefault(analysis_id, []).append(name)
    return tags


@dataclass(frozen=True, slots=True)
class ProcessMarks:
    tags: list[str]
    note_count: int


async def process_marks(session: AsyncSession, analysis_id: int) -> dict[str, ProcessMarks]:
    """The tag names (sorted) and the number of notes on each pid that has any, by pid."""
    tag_rows = await session.execute(
        select(TagLink.target_ref, Tag.name)
        .join(Tag, Tag.id == TagLink.tag_id)
        .where(TagLink.analysis_id == analysis_id, TagLink.target_type == TargetType.PROCESS)
        .order_by(Tag.name)
    )
    note_rows = await session.execute(
        select(Note.target_ref, func.count(Note.id))
        .where(Note.analysis_id == analysis_id, Note.target_type == TargetType.PROCESS)
        .group_by(Note.target_ref)
    )
    tags: dict[str, list[str]] = {}
    for ref, name in tag_rows:
        tags.setdefault(ref, []).append(name)
    note_counts = dict(note_rows.all())
    return {
        ref: ProcessMarks(tags.get(ref, []), note_counts.get(ref, 0))
        for ref in tags.keys() | note_counts.keys()
    }


async def add_note(session: AsyncSession, analysis_id: int, target: Target, body: str) -> Note:
    now = utc_now()
    note = Note(
        analysis_id=analysis_id,
        target_type=target.type,
        target_ref=target.ref,
        body=checked_note_body(body),
        created_at=now,
        updated_at=now,
    )
    session.add(note)
    await session.commit()
    return note


async def get_note(session: AsyncSession, note_id: int) -> Note | None:
    return await session.get(Note, note_id)


async def update_note(session: AsyncSession, note_id: int, body: str) -> Note | None:
    note = await session.get(Note, note_id)
    if note is None:
        return None
    note.body = checked_note_body(body)
    note.updated_at = utc_now()
    await session.commit()
    return note


async def delete_note(session: AsyncSession, note_id: int) -> bool:
    note = await session.get(Note, note_id)
    if note is None:
        return False
    await session.delete(note)
    await session.commit()
    return True


async def notes_of(
    session: AsyncSession,
    analysis_id: int,
    *,
    target_type: TargetType | None = None,
    target_ref: str | None = None,
) -> list[Note]:
    """The analysis's notes, oldest first; narrowed by the target if given."""
    statement = (
        select(Note)
        .where(Note.analysis_id == analysis_id, *_on_target(Note, target_type, target_ref))
        .order_by(Note.created_at, Note.id)
    )
    return list(await session.scalars(statement))


async def annotations_of_analysis(session: AsyncSession, analysis_id: int) -> AnalysisAnnotations:
    """Every tag and note of the analysis, whatever it is attached to."""
    return AnalysisAnnotations(
        tags=await tag_assignments(session, analysis_id),
        notes=await notes_of(session, analysis_id),
    )
