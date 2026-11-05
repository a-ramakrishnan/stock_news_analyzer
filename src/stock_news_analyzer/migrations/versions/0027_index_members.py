"""index_members: an index's constituents as NSE last listed them (the Nifty 50), for
comparing the portfolio's sector weights with the index's

Revision ID: 0027
Revises: 0026
Create Date: 2026-11-05 10:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0027"
down_revision: str | None = "0026"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "index_members",
        sa.Column("index_name", sa.String(length=64), nullable=False),
        sa.Column("isin", sa.String(length=12), nullable=False),
        sa.Column("symbol", sa.String(length=32), nullable=False),
        sa.Column("industry", sa.Text(), nullable=True),
        sa.Column(
            "listed_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.PrimaryKeyConstraint("index_name", "isin"),
    )


def downgrade() -> None:
    op.drop_table("index_members")
