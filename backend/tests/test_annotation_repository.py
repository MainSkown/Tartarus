from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import event, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.annotations.validation import Target
from app.db import analysis_repository
from app.db import annotation_repository as repository
from app.db.analysis_repository import AnalysisFilter
from app.db.base import Base
from app.db.models import Analysis, Note, Tag, TagLink
from app.db.models.annotation import TargetType
from tests.test_analysis_repository import SHA_B, seeded_analysis

WHOLE = Target(TargetType.ANALYSIS)
PROCESS_4 = Target(TargetType.PROCESS, "4")
EVENT_X = Target(TargetType.EVENT, "evt-x")


def _enable_foreign_keys(dbapi_connection: Any, _record: object) -> None:
    # SQLite skips foreign keys unless each connection enables them; Postgres always enforces them.
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


@pytest.fixture
async def session(tmp_path: Path) -> AsyncIterator[AsyncSession]:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'annotations.sqlite3'}")
    event.listen(engine.sync_engine, "connect", _enable_foreign_keys)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with async_sessionmaker(engine, expire_on_commit=False)() as db_session:
        yield db_session
    await engine.dispose()


async def count(session: AsyncSession, model: type[Base]) -> int:
    return int(await session.scalar(select(func.count()).select_from(model)) or 0)


async def test_a_tag_is_linked_to_its_target_and_listed_with_it(session: AsyncSession) -> None:
    analysis = await seeded_analysis(session)

    added = await repository.add_tag(session, analysis.id, PROCESS_4, "phishing")

    assert (added.tag, added.target_type, added.target_ref) == (
        "phishing",
        TargetType.PROCESS,
        "4",
    )
    assert await repository.tag_assignments(session, analysis.id) == [added]


async def test_tag_names_are_lowercased_so_one_name_is_one_tag(session: AsyncSession) -> None:
    first = await seeded_analysis(session)
    second = await seeded_analysis(session, filename="b.exe", sha256=SHA_B)

    await repository.add_tag(session, first.id, WHOLE, "Emotet")
    await repository.add_tag(session, second.id, WHOLE, "EMOTET")

    assert await count(session, Tag) == 1
    assert [(usage.name, usage.count) for usage in await repository.tag_usage(session)] == [
        ("emotet", 2)
    ]


@pytest.mark.parametrize("name", ["a" * 40, "a", "x.y_z-9", "needs-review"])
async def test_a_tag_name_of_up_to_40_allowed_characters_is_accepted(
    session: AsyncSession, name: str
) -> None:
    analysis = await seeded_analysis(session)

    added = await repository.add_tag(session, analysis.id, WHOLE, name)

    assert added.tag == name


@pytest.mark.parametrize("name", ["a" * 41, "", "has space", "snow☃", "slash/", "ünï", "a,b"])
async def test_a_tag_name_that_is_empty_too_long_or_uses_other_characters_is_refused(
    session: AsyncSession, name: str
) -> None:
    analysis = await seeded_analysis(session)

    with pytest.raises(ValueError, match="tag"):
        await repository.add_tag(session, analysis.id, WHOLE, name)

    assert await count(session, Tag) == 0


async def test_the_same_tag_on_the_same_target_twice_is_refused_and_changes_nothing(
    session: AsyncSession,
) -> None:
    analysis = await seeded_analysis(session)
    await repository.add_tag(session, analysis.id, PROCESS_4, "emotet")

    with pytest.raises(repository.TagLinkExistsError):
        await repository.add_tag(session, analysis.id, PROCESS_4, "EMOTET")

    assert await count(session, TagLink) == 1


async def test_one_tag_can_sit_on_other_targets_and_other_analyses(session: AsyncSession) -> None:
    first = await seeded_analysis(session)
    second = await seeded_analysis(session, filename="b.exe", sha256=SHA_B)

    for analysis_id, target in [
        (first.id, WHOLE),
        (first.id, PROCESS_4),
        (first.id, Target(TargetType.PROCESS, "5")),
        (first.id, EVENT_X),
        (second.id, WHOLE),
    ]:
        await repository.add_tag(session, analysis_id, target, "emotet")

    assert await count(session, TagLink) == 5
    assert await count(session, Tag) == 1


async def test_the_database_itself_refuses_a_duplicate_link(session: AsyncSession) -> None:
    analysis = await seeded_analysis(session)
    await repository.add_tag(session, analysis.id, WHOLE, "emotet")
    tag = (await session.scalars(select(Tag))).one()

    session.add(TagLink(tag_id=tag.id, analysis_id=analysis.id, target_type=TargetType.ANALYSIS))
    with pytest.raises(IntegrityError):
        await session.commit()
    await session.rollback()


async def test_assignments_can_be_narrowed_to_one_target(session: AsyncSession) -> None:
    analysis = await seeded_analysis(session)
    await repository.add_tag(session, analysis.id, WHOLE, "a")
    await repository.add_tag(session, analysis.id, PROCESS_4, "b")
    await repository.add_tag(session, analysis.id, Target(TargetType.PROCESS, "5"), "c")

    on_process = await repository.tag_assignments(
        session, analysis.id, target_type=TargetType.PROCESS, target_ref="4"
    )
    on_any_process = await repository.tag_assignments(
        session, analysis.id, target_type=TargetType.PROCESS
    )

    assert [assignment.tag for assignment in on_process] == ["b"]
    assert [assignment.tag for assignment in on_any_process] == ["b", "c"]


async def test_removing_a_link_deletes_a_tag_nothing_else_uses(session: AsyncSession) -> None:
    analysis = await seeded_analysis(session)
    link = await repository.add_tag(session, analysis.id, WHOLE, "emotet")

    removed = await repository.remove_tag_link(session, analysis.id, link.link_id)

    assert removed is True
    assert await count(session, TagLink) == 0
    assert await count(session, Tag) == 0
    assert await repository.tag_usage(session) == []


async def test_removing_a_link_keeps_a_tag_another_link_still_uses(session: AsyncSession) -> None:
    analysis = await seeded_analysis(session)
    link = await repository.add_tag(session, analysis.id, WHOLE, "emotet")
    await repository.add_tag(session, analysis.id, PROCESS_4, "emotet")

    await repository.remove_tag_link(session, analysis.id, link.link_id)

    assert [(u.name, u.count) for u in await repository.tag_usage(session)] == [("emotet", 1)]


async def test_a_link_of_another_analysis_is_not_removed(session: AsyncSession) -> None:
    first = await seeded_analysis(session)
    second = await seeded_analysis(session, filename="b.exe", sha256=SHA_B)
    link = await repository.add_tag(session, first.id, WHOLE, "emotet")

    removed = await repository.remove_tag_link(session, second.id, link.link_id)

    assert removed is False
    assert await count(session, TagLink) == 1


async def test_removing_an_unknown_link_says_so(session: AsyncSession) -> None:
    analysis = await seeded_analysis(session)

    assert await repository.remove_tag_link(session, analysis.id, 999) is False


async def test_usage_counts_links_across_analyses_most_used_first_then_by_name(
    session: AsyncSession,
) -> None:
    first = await seeded_analysis(session)
    second = await seeded_analysis(session, filename="b.exe", sha256=SHA_B)
    for analysis_id, target, name in [
        (first.id, WHOLE, "zeta"),
        (first.id, PROCESS_4, "alpha"),
        (second.id, WHOLE, "alpha"),
        (second.id, PROCESS_4, "mid"),
        (second.id, EVENT_X, "beta"),
    ]:
        await repository.add_tag(session, analysis_id, target, name)

    usage = [(u.name, u.count) for u in await repository.tag_usage(session)]

    assert usage == [("alpha", 2), ("beta", 1), ("mid", 1), ("zeta", 1)]


async def test_deleting_an_analysis_removes_its_links_and_notes_and_leaves_no_unused_tag(
    session: AsyncSession,
) -> None:
    doomed = await seeded_analysis(session)
    kept = await seeded_analysis(session, filename="b.exe", sha256=SHA_B)
    await repository.add_tag(session, doomed.id, WHOLE, "only-here")
    await repository.add_tag(session, doomed.id, WHOLE, "shared")
    await repository.add_tag(session, kept.id, PROCESS_4, "shared")
    await repository.add_note(session, doomed.id, EVENT_X, "gone with it")
    await repository.add_note(session, kept.id, WHOLE, "stays")

    await analysis_repository.delete_analysis(session, doomed.id)

    assert [(u.name, u.count) for u in await repository.tag_usage(session)] == [("shared", 1)]
    assert await count(session, Tag) == 1
    assert [note.body for note in (await session.scalars(select(Note))).all()] == ["stays"]
    assert await count(session, TagLink) == 1


async def test_a_note_is_stored_with_its_target_and_times(session: AsyncSession) -> None:
    analysis = await seeded_analysis(session)

    note = await repository.add_note(session, analysis.id, PROCESS_4, "dropper stage two")

    assert (note.analysis_id, note.target_type, note.target_ref, note.body) == (
        analysis.id,
        TargetType.PROCESS,
        "4",
        "dropper stage two",
    )
    assert note.created_at is not None
    assert note.updated_at == note.created_at


@pytest.mark.parametrize("length", [1, 20_000])
async def test_a_note_of_1_to_20000_characters_is_accepted(
    session: AsyncSession, length: int
) -> None:
    analysis = await seeded_analysis(session)

    note = await repository.add_note(session, analysis.id, WHOLE, "n" * length)

    assert len(note.body) == length


@pytest.mark.parametrize("body", ["", "   \n\t", "n" * 20_001])
async def test_a_blank_or_too_long_note_is_refused(session: AsyncSession, body: str) -> None:
    analysis = await seeded_analysis(session)

    with pytest.raises(ValueError, match="note"):
        await repository.add_note(session, analysis.id, WHOLE, body)

    assert await count(session, Note) == 0


async def test_a_note_keeps_its_text_as_written(session: AsyncSession) -> None:
    analysis = await seeded_analysis(session)

    note = await repository.add_note(session, analysis.id, WHOLE, "  line one\nline two  ")

    assert note.body == "  line one\nline two  "


async def test_updating_a_note_replaces_its_text_and_moves_updated_at_only(
    session: AsyncSession,
) -> None:
    analysis = await seeded_analysis(session)
    note = await repository.add_note(session, analysis.id, WHOLE, "first")

    changed = await repository.update_note(session, note.id, "second")

    assert changed is not None
    assert changed.body == "second"
    assert changed.created_at == note.created_at
    assert changed.updated_at > changed.created_at


async def test_updating_a_note_checks_the_text_like_creating_it(session: AsyncSession) -> None:
    analysis = await seeded_analysis(session)
    note = await repository.add_note(session, analysis.id, WHOLE, "first")

    with pytest.raises(ValueError, match="note"):
        await repository.update_note(session, note.id, "n" * 20_001)

    assert (await session.get(Note, note.id)).body == "first"  # type: ignore[union-attr]


async def test_updating_or_deleting_an_unknown_note_says_so(session: AsyncSession) -> None:
    assert await repository.update_note(session, 999, "x") is None
    assert await repository.delete_note(session, 999) is False


async def test_a_deleted_note_is_gone(session: AsyncSession) -> None:
    analysis = await seeded_analysis(session)
    note = await repository.add_note(session, analysis.id, WHOLE, "first")

    assert await repository.delete_note(session, note.id) is True
    assert await repository.notes_of(session, analysis.id) == []


async def test_notes_are_listed_oldest_first_and_can_be_narrowed_to_a_target(
    session: AsyncSession,
) -> None:
    analysis = await seeded_analysis(session)
    await repository.add_note(session, analysis.id, PROCESS_4, "p4")
    await repository.add_note(session, analysis.id, WHOLE, "whole")
    await repository.add_note(session, analysis.id, PROCESS_4, "p4 again")

    everything = await repository.notes_of(session, analysis.id)
    on_process = await repository.notes_of(
        session, analysis.id, target_type=TargetType.PROCESS, target_ref="4"
    )
    on_any_event = await repository.notes_of(session, analysis.id, target_type=TargetType.EVENT)

    assert [note.body for note in everything] == ["p4", "whole", "p4 again"]
    assert [note.body for note in on_process] == ["p4", "p4 again"]
    assert on_any_event == []


async def test_the_annotations_of_an_analysis_come_grouped_for_the_exporters(
    session: AsyncSession,
) -> None:
    analysis = await seeded_analysis(session)
    other = await seeded_analysis(session, filename="b.exe", sha256=SHA_B)
    await repository.add_tag(session, analysis.id, WHOLE, "phishing")
    await repository.add_tag(session, analysis.id, EVENT_X, "c2")
    await repository.add_tag(session, other.id, WHOLE, "unrelated")
    await repository.add_note(session, analysis.id, WHOLE, "overall")
    await repository.add_note(session, other.id, WHOLE, "not mine")

    grouped = await repository.annotations_of_analysis(session, analysis.id)

    assert sorted(assignment.tag for assignment in grouped.tags) == ["c2", "phishing"]
    assert [note.body for note in grouped.notes] == ["overall"]


async def test_the_tags_on_the_analysis_itself_are_listed_for_many_analyses_at_once(
    session: AsyncSession,
) -> None:
    first = await seeded_analysis(session)
    second = await seeded_analysis(session, filename="b.exe", sha256=SHA_B)
    third = await seeded_analysis(session, filename="c.exe", sha256="c" * 64)
    await repository.add_tag(session, first.id, WHOLE, "zeta")
    await repository.add_tag(session, first.id, WHOLE, "alpha")
    await repository.add_tag(session, first.id, PROCESS_4, "on-a-process")
    await repository.add_tag(session, second.id, EVENT_X, "on-an-event")

    tags = await repository.analysis_level_tags(session, [first.id, second.id, third.id])

    assert tags == {first.id: ["alpha", "zeta"]}


async def test_analyses_can_be_filtered_by_a_tag_on_the_analysis_itself(
    session: AsyncSession,
) -> None:
    tagged = await seeded_analysis(session)
    only_a_process = await seeded_analysis(session, filename="b.exe", sha256=SHA_B)
    await seeded_analysis(session, filename="c.exe", sha256="c" * 64)
    await repository.add_tag(session, tagged.id, WHOLE, "emotet")
    await repository.add_tag(session, only_a_process.id, PROCESS_4, "emotet")
    filters = AnalysisFilter(tag="Emotet")

    found = await analysis_repository.list_analyses(session, filters)

    assert [analysis.id for analysis in found] == [tagged.id]
    assert await analysis_repository.count_analyses(session, filters) == 1


async def test_a_tag_filter_for_an_unused_tag_matches_nothing(session: AsyncSession) -> None:
    await seeded_analysis(session)

    found = await analysis_repository.list_analyses(session, AnalysisFilter(tag="nothing"))

    assert found == []


async def test_annotations_of_one_analysis_survive_changes_to_that_analysis_row(
    session: AsyncSession,
) -> None:
    analysis = await seeded_analysis(session)
    await repository.add_tag(session, analysis.id, EVENT_X, "c2")
    await repository.add_note(session, analysis.id, EVENT_X, "beacon")

    await analysis_repository.update_analysis(session, analysis.id, event_count=0)
    stored = await session.get(Analysis, analysis.id)

    assert stored is not None
    grouped = await repository.annotations_of_analysis(session, analysis.id)
    assert (len(grouped.tags), len(grouped.notes)) == (1, 1)
