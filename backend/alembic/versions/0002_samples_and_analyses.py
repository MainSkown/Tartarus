"""create sample and analysis tables

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-13

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ANALYSIS_STATUSES = (
    "queued",
    "starting",
    "running",
    "processing",
    "ingesting",
    "done",
    "failed",
    "report_failed",
    "cancelled",
)
ANALYSIS_PHASES = ("live", "final")
SEVERITIES = ("info", "low", "medium", "high", "critical")


def upgrade() -> None:
    op.create_table(
        "sample",
        sa.Column("sha256", sa.Text(), nullable=False),
        sa.Column("sha1", sa.Text(), nullable=False),
        sa.Column("md5", sa.Text(), nullable=False),
        sa.Column("size", sa.BigInteger(), nullable=False),
        sa.Column("file_type", sa.Text(), nullable=True),
        sa.Column("original_name", sa.Text(), nullable=False),
        sa.Column("stored_path", sa.Text(), nullable=False),
        sa.Column("first_seen", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("sha256", name=op.f("pk_sample")),
    )
    op.create_table(
        "analysis",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("sample_sha256", sa.Text(), nullable=False),
        sa.Column("filename", sa.Text(), nullable=False),
        sa.Column("cape_task_id", sa.Integer(), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                *ANALYSIS_STATUSES,
                name=op.f("ck_analysis_analysis_status"),
                native_enum=False,
                create_constraint=True,
                length=13,
            ),
            nullable=False,
        ),
        sa.Column(
            "phase",
            sa.Enum(
                *ANALYSIS_PHASES,
                name=op.f("ck_analysis_analysis_phase"),
                native_enum=False,
                create_constraint=True,
                length=5,
            ),
            nullable=False,
        ),
        sa.Column("options", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("score", sa.Numeric(precision=3, scale=1), nullable=True),
        sa.Column(
            "max_severity",
            sa.Enum(
                *SEVERITIES,
                name=op.f("ck_analysis_analysis_max_severity"),
                native_enum=False,
                create_constraint=True,
                length=8,
            ),
            nullable=True,
        ),
        sa.Column("detected_families", postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column("event_count", sa.BigInteger(), nullable=False),
        sa.Column("disk_bytes", sa.BigInteger(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("summary", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.ForeignKeyConstraint(
            ["sample_sha256"],
            ["sample.sha256"],
            name=op.f("fk_analysis_sample_sha256_sample"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_analysis")),
    )
    op.create_index(op.f("ix_analysis_sample_sha256"), "analysis", ["sample_sha256"])


def downgrade() -> None:
    op.drop_index(op.f("ix_analysis_sample_sha256"), table_name="analysis")
    op.drop_table("analysis")
    op.drop_table("sample")
