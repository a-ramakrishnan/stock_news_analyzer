"""llm_traces and llm_prompts: what each AI call was sent and what it answered (the prompt, the
answer, the stop reason, the model that served it, how long it took), with each distinct set of
instructions stored once; kept for `llm_trace_days`

Revision ID: 0033
Revises: 0032
Create Date: 2026-11-05 22:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0033"
down_revision: str | None = "0032"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "llm_prompts",
        sa.Column("sha", sa.String(length=64), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("sha"),
    )
    op.create_table(
        "llm_traces",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("call_id", sa.Integer(), nullable=False),
        sa.Column("system_sha", sa.String(length=64)),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("response", postgresql.JSONB()),
        sa.Column("stop_reason", sa.String(length=32)),
        sa.Column("served_model", sa.String(length=64)),
        sa.Column("latency_ms", sa.Integer()),
        sa.Column("subjects", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.ForeignKeyConstraint(["call_id"], ["llm_calls.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["system_sha"], ["llm_prompts.sha"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("call_id", name="llm_traces_call_id"),
    )


def downgrade() -> None:
    op.drop_table("llm_traces")
    op.drop_table("llm_prompts")
