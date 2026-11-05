"""balance_sheets: a company's balance sheet and cash flow at each half year and year end,
from its results XBRL

Revision ID: 0028
Revises: 0027
Create Date: 2026-11-05 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0028"
down_revision: str | None = "0027"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "balance_sheets",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("isin", sa.String(length=12), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("months", sa.Integer(), nullable=False),
        sa.Column("basis", sa.String(length=16), nullable=False),
        sa.Column("equity_cr", sa.Numeric(16, 2), nullable=True),
        sa.Column("borrowings_cr", sa.Numeric(16, 2), nullable=True),
        sa.Column("cash_cr", sa.Numeric(16, 2), nullable=True),
        sa.Column("total_assets_cr", sa.Numeric(16, 2), nullable=True),
        sa.Column("cfo_cr", sa.Numeric(16, 2), nullable=True),
        sa.Column("capex_cr", sa.Numeric(16, 2), nullable=True),
        sa.Column("as_written", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("source", sa.Text(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["isin"], ["companies.isin"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("isin", "period_end", name="uq_balance_sheets_isin_end"),
    )
    op.create_index("ix_balance_sheets_isin", "balance_sheets", ["isin"])


def downgrade() -> None:
    op.drop_index("ix_balance_sheets_isin", table_name="balance_sheets")
    op.drop_table("balance_sheets")
