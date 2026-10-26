"""results and result filings

Revision ID: 0016
Revises: 0015
Create Date: 2026-10-26 07:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0016"
down_revision: str | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "result_filings",
        sa.Column("document_id", sa.Integer(), nullable=False),
        sa.Column("isin", sa.String(length=12), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("period", sa.String(length=16), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("model", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["isin"], ["companies.isin"]),
        sa.PrimaryKeyConstraint("document_id"),
    )
    op.create_index(op.f("ix_result_filings_isin"), "result_filings", ["isin"], unique=False)
    op.create_table(
        "results",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("isin", sa.String(length=12), nullable=False),
        sa.Column("period", sa.String(length=16), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("months", sa.Integer(), nullable=False),
        sa.Column("basis", sa.String(length=16), nullable=False),
        sa.Column("document_id", sa.Integer(), nullable=True),
        sa.Column("primary", sa.Boolean(), nullable=False),
        sa.Column("revenue_cr", sa.Numeric(precision=14, scale=2), nullable=True),
        sa.Column("other_income_cr", sa.Numeric(precision=14, scale=2), nullable=True),
        sa.Column("finance_costs_cr", sa.Numeric(precision=14, scale=2), nullable=True),
        sa.Column("depreciation_cr", sa.Numeric(precision=14, scale=2), nullable=True),
        sa.Column("pbt_cr", sa.Numeric(precision=14, scale=2), nullable=True),
        sa.Column("pat_cr", sa.Numeric(precision=14, scale=2), nullable=True),
        sa.Column("eps", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("unit", sa.String(length=16), nullable=False),
        sa.Column("as_written", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("model", sa.String(length=64), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["isin"], ["companies.isin"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("isin", "period_end", "months", name="result_period"),
    )
    op.create_index(op.f("ix_results_isin"), "results", ["isin"], unique=False)
    op.create_index(op.f("ix_results_period_end"), "results", ["period_end"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_results_period_end"), table_name="results")
    op.drop_index(op.f("ix_results_isin"), table_name="results")
    op.drop_table("results")
    op.drop_index(op.f("ix_result_filings_isin"), table_name="result_filings")
    op.drop_table("result_filings")
