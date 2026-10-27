"""theme tags and peer signals

Revision ID: 0022
Revises: 0021
Create Date: 2026-10-27 18:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0022"
down_revision: str | None = "0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "theme_tags",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("item_type", sa.String(length=16), nullable=False),
        sa.Column("item_id", sa.BigInteger(), nullable=False),
        sa.Column("theme", sa.String(length=32), nullable=False),
        sa.Column("isin", sa.String(length=12), nullable=False),
        sa.Column("on_date", sa.Date(), nullable=False),
        sa.Column("value_cr", sa.Numeric(precision=16, scale=4), nullable=True),
        sa.Column("sentiment", sa.String(length=16), nullable=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("model", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["isin"], ["companies.isin"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("item_type", "item_id", "theme", name="theme_tag_item"),
    )
    op.create_index(op.f("ix_theme_tags_isin"), "theme_tags", ["isin"], unique=False)
    op.create_index(op.f("ix_theme_tags_on_date"), "theme_tags", ["on_date"], unique=False)
    op.create_index(op.f("ix_theme_tags_theme"), "theme_tags", ["theme"], unique=False)
    op.create_table(
        "peer_signals",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("source_type", sa.String(length=16), nullable=False),
        sa.Column("source_id", sa.BigInteger(), nullable=False),
        sa.Column("source_isin", sa.String(length=12), nullable=False),
        sa.Column("target_isin", sa.String(length=12), nullable=False),
        sa.Column("relation", sa.String(length=48), nullable=False),
        sa.Column("on_date", sa.Date(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["source_isin"], ["companies.isin"]),
        sa.ForeignKeyConstraint(["target_isin"], ["companies.isin"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source_type", "source_id", "target_isin", name="peer_signal_target"),
    )
    op.create_index(op.f("ix_peer_signals_on_date"), "peer_signals", ["on_date"], unique=False)
    op.create_index(op.f("ix_peer_signals_source_isin"), "peer_signals", ["source_isin"])
    op.create_index(op.f("ix_peer_signals_target_isin"), "peer_signals", ["target_isin"])


def downgrade() -> None:
    op.drop_table("peer_signals")
    op.drop_table("theme_tags")
