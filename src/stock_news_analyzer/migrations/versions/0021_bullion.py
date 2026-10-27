"""market series and bullion moves

Revision ID: 0021
Revises: 0020
Create Date: 2026-10-27 16:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0021"
down_revision: str | None = "0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "market_series",
        sa.Column("series", sa.String(length=16), nullable=False),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("close", sa.Numeric(precision=16, scale=4), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.PrimaryKeyConstraint("series", "trade_date"),
    )
    op.create_table(
        "bullion_moves",
        sa.Column("metal", sa.String(length=8), nullable=False),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("symbol", sa.String(length=32), nullable=False),
        sa.Column("close", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column("inr_return", sa.Float(), nullable=False),
        sa.Column("global_return", sa.Float(), nullable=True),
        sa.Column("fx_return", sa.Float(), nullable=True),
        sa.Column("other_return", sa.Float(), nullable=True),
        sa.Column("zscore", sa.Float(), nullable=True),
        sa.Column("unusual", sa.Boolean(), nullable=False),
        sa.Column("driver", sa.String(length=16), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("evidence", postgresql.ARRAY(sa.BigInteger()), nullable=False),
        sa.Column("model", sa.String(length=64), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("metal", "trade_date"),
    )
    op.create_index(op.f("ix_bullion_moves_unusual"), "bullion_moves", ["unusual"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_bullion_moves_unusual"), table_name="bullion_moves")
    op.drop_table("bullion_moves")
    op.drop_table("market_series")
