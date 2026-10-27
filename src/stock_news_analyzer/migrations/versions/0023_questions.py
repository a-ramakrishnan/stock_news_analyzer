"""questions, and a full-text index on documents

Revision ID: 0023
Revises: 0022
Create Date: 2026-10-27 20:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0023"
down_revision: str | None = "0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# The expression agents/ask.py searches with; the index is used only when they match exactly.
DOCUMENT_TSV = (
    "to_tsvector('english', coalesce(title, '') || ' ' || left(coalesce(text, ''), 20000))"
)


def upgrade() -> None:
    op.create_table(
        "questions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column(
            "asked_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("name", sa.String(length=64), nullable=True),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("answer", sa.Text(), nullable=False),
        sa.Column("sources", postgresql.ARRAY(sa.Text()), server_default="{}", nullable=False),
        sa.Column("steps", sa.Integer(), nullable=False),
        sa.Column("model", sa.String(length=64), nullable=False),
        sa.Column("cost_usd", sa.Numeric(precision=10, scale=5), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_questions_name"), "questions", ["name"], unique=False)
    op.execute(f"CREATE INDEX ix_documents_tsv ON documents USING gin ({DOCUMENT_TSV})")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_documents_tsv")
    op.drop_index(op.f("ix_questions_name"), table_name="questions")
    op.drop_table("questions")
