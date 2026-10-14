"""create the job table

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-15

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JOB_TYPES = ("guest_build", "ingest", "reingest", "export_report", "delete_analysis")
JOB_STATUSES = ("pending", "running", "done", "failed", "interrupted")


def upgrade() -> None:
    op.create_table(
        "job",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column(
            "type",
            sa.Enum(
                *JOB_TYPES,
                name=op.f("ck_job_job_type"),
                native_enum=False,
                create_constraint=True,
                length=15,
            ),
            nullable=False,
        ),
        sa.Column("analysis_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                *JOB_STATUSES,
                name=op.f("ck_job_job_status"),
                native_enum=False,
                create_constraint=True,
                length=11,
            ),
            nullable=False,
        ),
        sa.Column("step", sa.Text(), nullable=False),
        sa.Column("progress", sa.Integer(), nullable=False),
        sa.Column("log", sa.Text(), nullable=False),
        sa.Column("result", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("progress BETWEEN 0 AND 100", name=op.f("ck_job_progress_range")),
        sa.ForeignKeyConstraint(
            ["analysis_id"],
            ["analysis.id"],
            name=op.f("fk_job_analysis_id_analysis"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_job")),
    )
    op.create_index(op.f("ix_job_analysis_id"), "job", ["analysis_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_job_analysis_id"), table_name="job")
    op.drop_table("job")
