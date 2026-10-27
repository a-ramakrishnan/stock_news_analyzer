"""shareholdings: quarterly shareholding patterns

Revision ID: 0024
Revises: 0023
Create Date: 2026-10-28 09:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0024"
down_revision: str | None = "0023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PCT = sa.Numeric(precision=7, scale=4)


def upgrade() -> None:
    op.create_table(
        "shareholdings",
        sa.Column("isin", sa.String(length=12), nullable=False),
        sa.Column("quarter_end", sa.Date(), nullable=False),
        sa.Column("filed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("record_id", sa.String(length=32), nullable=False),
        sa.Column("xbrl_url", sa.Text(), nullable=False),
        sa.Column("total_shares", sa.BigInteger(), nullable=True),
        sa.Column("shareholders", sa.Integer(), nullable=True),
        sa.Column("promoter_pct", PCT, nullable=True),
        sa.Column("public_pct", PCT, nullable=True),
        sa.Column("fii_pct", PCT, nullable=True),
        sa.Column("dii_pct", PCT, nullable=True),
        sa.Column("mf_pct", PCT, nullable=True),
        sa.Column("insurance_pct", PCT, nullable=True),
        sa.Column("retail_pct", PCT, nullable=True),
        sa.Column("promoter_shares", sa.BigInteger(), nullable=True),
        sa.Column("pledged_pct", PCT, nullable=True),
        sa.Column("locked_pct", PCT, nullable=True),
        sa.Column("categories", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["isin"], ["companies.isin"]),
        sa.PrimaryKeyConstraint("isin", "quarter_end"),
    )
    op.create_index(
        op.f("ix_shareholdings_quarter_end"), "shareholdings", ["quarter_end"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_shareholdings_quarter_end"), table_name="shareholdings")
    op.drop_table("shareholdings")
