"""create the tag, tag_link and note tables

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-14

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TARGET_TYPES = ("analysis", "process", "event")


def _target_type(constraint_name: str) -> sa.Enum:
    return sa.Enum(
        *TARGET_TYPES,
        name=op.f(constraint_name),
        native_enum=False,
        create_constraint=True,
        length=8,
    )


def upgrade() -> None:
    op.create_table(
        "tag",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tag")),
        sa.UniqueConstraint("name", name=op.f("uq_tag_name")),
    )
    op.create_table(
        "tag_link",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("tag_id", sa.BigInteger(), nullable=False),
        sa.Column("analysis_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "target_type", _target_type("ck_tag_link_annotation_target_type"), nullable=False
        ),
        sa.Column("target_ref", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(
            ["tag_id"], ["tag.id"], name=op.f("fk_tag_link_tag_id_tag"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["analysis_id"],
            ["analysis.id"],
            name=op.f("fk_tag_link_analysis_id_analysis"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tag_link")),
        sa.UniqueConstraint(
            "tag_id",
            "analysis_id",
            "target_type",
            "target_ref",
            name=op.f("uq_tag_link_tag_id"),
        ),
    )
    op.create_index(op.f("ix_tag_link_tag_id"), "tag_link", ["tag_id"])
    op.create_index(op.f("ix_tag_link_analysis_id"), "tag_link", ["analysis_id"])
    op.create_table(
        "note",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("analysis_id", sa.BigInteger(), nullable=False),
        sa.Column("target_type", _target_type("ck_note_annotation_target_type"), nullable=False),
        sa.Column("target_ref", sa.Text(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["analysis_id"],
            ["analysis.id"],
            name=op.f("fk_note_analysis_id_analysis"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_note")),
    )
    op.create_index(op.f("ix_note_analysis_id"), "note", ["analysis_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_note_analysis_id"), table_name="note")
    op.drop_table("note")
    op.drop_index(op.f("ix_tag_link_analysis_id"), table_name="tag_link")
    op.drop_index(op.f("ix_tag_link_tag_id"), table_name="tag_link")
    op.drop_table("tag_link")
    op.drop_table("tag")
