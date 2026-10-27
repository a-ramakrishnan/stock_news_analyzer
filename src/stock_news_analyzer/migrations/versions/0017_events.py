"""events and event filings

Revision ID: 0017
Revises: 0016
Create Date: 2026-10-27 07:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0017"
down_revision: str | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "event_filings",
        sa.Column("document_id", sa.Integer(), nullable=False),
        sa.Column("isin", sa.String(length=12), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
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
    op.create_index(op.f("ix_event_filings_isin"), "event_filings", ["isin"], unique=False)
    op.create_table(
        "events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("isin", sa.String(length=12), nullable=False),
        sa.Column("document_id", sa.Integer(), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("event_type", sa.String(length=24), nullable=False),
        sa.Column("headline", sa.Text(), nullable=False),
        sa.Column("event_date", sa.Date(), nullable=True),
        sa.Column("sentiment", sa.String(length=16), nullable=False),
        sa.Column("importance", sa.Integer(), nullable=False),
        sa.Column("value_cr", sa.Numeric(precision=14, scale=2), nullable=True),
        sa.Column("value_as_written", sa.Text(), nullable=True),
        sa.Column("value_kind", sa.Text(), nullable=True),
        sa.Column("materiality", sa.Float(), nullable=True),
        sa.Column("counterparty", sa.Text(), nullable=True),
        sa.Column("person", sa.Text(), nullable=True),
        sa.Column("role", sa.Text(), nullable=True),
        sa.Column("action", sa.Text(), nullable=True),
        sa.Column("rating_from", sa.Text(), nullable=True),
        sa.Column("rating_to", sa.Text(), nullable=True),
        sa.Column("stake_pct", sa.Float(), nullable=True),
        sa.Column("quote", sa.Text(), nullable=True),
        sa.Column("quote_found", sa.Boolean(), nullable=False),
        sa.Column("qa_status", sa.String(length=16), server_default="pending", nullable=False),
        sa.Column("qa_notes", postgresql.ARRAY(sa.Text()), server_default="{}", nullable=False),
        sa.Column("duplicate_of", sa.Integer(), nullable=True),
        sa.Column("qa_model", sa.String(length=64), nullable=True),
        sa.Column("review", sa.String(length=16), nullable=True),
        sa.Column("review_note", sa.Text(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("model", sa.String(length=64), nullable=False),
        sa.Column("prompt_version", sa.String(length=16), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["duplicate_of"], ["events.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["isin"], ["companies.isin"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_events_document_id"), "events", ["document_id"], unique=False)
    op.create_index(op.f("ix_events_event_type"), "events", ["event_type"], unique=False)
    op.create_index(op.f("ix_events_isin"), "events", ["isin"], unique=False)
    op.create_index(op.f("ix_events_published_at"), "events", ["published_at"], unique=False)
    op.create_index(op.f("ix_events_qa_status"), "events", ["qa_status"], unique=False)


def downgrade() -> None:
    op.drop_table("events")
    op.drop_index(op.f("ix_event_filings_isin"), table_name="event_filings")
    op.drop_table("event_filings")
