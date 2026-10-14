"""create the sigma_rule table

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-14

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

VALIDITIES = ("valid", "invalid", "unsupported")


def upgrade() -> None:
    op.create_table(
        "sigma_rule",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("level", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=True),
        sa.Column("path", sa.Text(), nullable=False),
        sa.Column("content_sha256", sa.Text(), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column(
            "validity",
            sa.Enum(
                *VALIDITIES,
                name=op.f("ck_sigma_rule_sigma_rule_validity"),
                native_enum=False,
                create_constraint=True,
                length=11,
            ),
            nullable=False,
        ),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("loaded_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sigma_rule")),
    )


def downgrade() -> None:
    op.drop_table("sigma_rule")
