"""research_briefs: each AI-written view of a stock's research brief, with the facts it was
given, so every version is kept and can be compared

Revision ID: 0029
Revises: 0028
Create Date: 2026-11-05 14:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0029"
down_revision: str | None = "0028"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "research_briefs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("isin", sa.String(length=12), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("model", sa.String(length=64), nullable=False),
        sa.Column("cost_usd", sa.Numeric(10, 5), nullable=False, server_default="0"),
        sa.Column("facts", postgresql.JSONB(), nullable=False),
        sa.Column("view", postgresql.JSONB(), nullable=False),
        sa.Column("dropped", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.ForeignKeyConstraint(["isin"], ["companies.isin"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_research_briefs_isin", "research_briefs", ["isin"])


def downgrade() -> None:
    op.drop_index("ix_research_briefs_isin", table_name="research_briefs")
    op.drop_table("research_briefs")
