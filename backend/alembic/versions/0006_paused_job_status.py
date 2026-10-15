"""allow the paused job status

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-15

"""

from collections.abc import Sequence

from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

STATUS_CHECK = op.f("ck_job_job_status")
STATUSES_BEFORE = ("pending", "running", "done", "failed", "interrupted")
STATUSES_AFTER = ("pending", "running", "paused", "done", "failed", "interrupted")


def _replace_status_check(statuses: Sequence[str]) -> None:
    allowed = ", ".join(f"'{status}'" for status in statuses)
    op.drop_constraint(STATUS_CHECK, "job", type_="check")
    op.create_check_constraint(STATUS_CHECK, "job", f"status IN ({allowed})")


def upgrade() -> None:
    _replace_status_check(STATUSES_AFTER)


def downgrade() -> None:
    # No process is left to resume a paused job; `interrupted` is the old schema's closest status.
    op.execute("UPDATE job SET status='interrupted' WHERE status='paused'")
    _replace_status_check(STATUSES_BEFORE)
