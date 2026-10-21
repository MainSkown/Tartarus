"""tell an analysed run from an imported file

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-21

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ANALYSIS_KINDS = ("run", "imported")


def upgrade() -> None:
    op.add_column(
        "analysis",
        sa.Column(
            "kind",
            sa.Enum(
                *ANALYSIS_KINDS,
                name=op.f("ck_analysis_analysis_kind"),
                native_enum=False,
                create_constraint=True,
                length=8,
            ),
            server_default="run",
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("analysis", "kind")
