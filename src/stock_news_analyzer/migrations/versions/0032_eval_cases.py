"""eval_cases: the cases of every agent's eval (its input frozen, the expected answer, whether
you checked it, and every earlier version of the answer), so evals share one framework and
cases can be labelled in the dashboard

Revision ID: 0032
Revises: 0031
Create Date: 2026-11-05 21:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0032"
down_revision: str | None = "0031"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "eval_cases",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("dataset", sa.String(length=32), nullable=False),
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("title", sa.Text()),
        sa.Column("tags", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("input", postgresql.JSONB(), nullable=False),
        sa.Column("reference", postgresql.JSONB()),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="new"),
        sa.Column("drafted_by", sa.String(length=64)),
        sa.Column("note", sa.Text()),
        sa.Column("history", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("dataset", "key", name="eval_cases_dataset_key"),
    )
    op.create_index("ix_eval_cases_dataset", "eval_cases", ["dataset"])


def downgrade() -> None:
    op.drop_index("ix_eval_cases_dataset", table_name="eval_cases")
    op.drop_table("eval_cases")
