"""red flags

Revision ID: 0019
Revises: 0018
Create Date: 2026-10-27 14:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0019"
down_revision: str | None = "0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "red_flags",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("isin", sa.String(length=12), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("severity", sa.String(length=8), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column("flagged_on", sa.Date(), nullable=False),
        sa.Column("ref", sa.String(length=64), nullable=False),
        sa.Column("event_id", sa.Integer(), nullable=True),
        sa.Column("document_id", sa.Integer(), nullable=True),
        sa.Column("dismissed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["event_id"], ["events.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["isin"], ["companies.isin"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("isin", "kind", "ref", name="red_flag_ref"),
    )
    op.create_index(op.f("ix_red_flags_flagged_on"), "red_flags", ["flagged_on"], unique=False)
    op.create_index(op.f("ix_red_flags_isin"), "red_flags", ["isin"], unique=False)
    op.create_index(op.f("ix_red_flags_kind"), "red_flags", ["kind"], unique=False)
    op.create_index(op.f("ix_red_flags_severity"), "red_flags", ["severity"], unique=False)


def downgrade() -> None:
    op.drop_table("red_flags")
