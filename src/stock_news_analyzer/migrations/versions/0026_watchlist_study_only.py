"""watchlist.study_only: stocks followed for the evidence (the Nifty 50), without the costly
AI work (earnings calls, promises, move explanations) or a card on Today

Revision ID: 0026
Revises: 0025
Create Date: 2026-11-04 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0026"
down_revision: str | None = "0025"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "watchlist",
        sa.Column("study_only", sa.Boolean(), server_default="false", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("watchlist", "study_only")
