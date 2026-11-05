"""eval_runs.config and note: what a run changed (model, instructions) and why, so experiments
can be compared knowing what differs

Revision ID: 0034
Revises: 0033
Create Date: 2026-11-05 23:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0034"
down_revision: str | None = "0033"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "eval_runs",
        sa.Column("config", postgresql.JSONB(), nullable=False, server_default="{}"),
    )
    op.add_column("eval_runs", sa.Column("note", sa.Text()))


def downgrade() -> None:
    op.drop_column("eval_runs", "note")
    op.drop_column("eval_runs", "config")
