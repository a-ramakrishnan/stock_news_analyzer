"""event amounts to four decimals of a crore

Revision ID: 0018
Revises: 0017
Create Date: 2026-10-27 13:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0018"
down_revision: str | None = "0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Two decimals of a crore is Rs 1 lakh: small penalties lost most of their value.
    op.alter_column(
        "events",
        "value_cr",
        type_=sa.Numeric(precision=16, scale=4),
        existing_type=sa.Numeric(precision=14, scale=2),
    )


def downgrade() -> None:
    op.alter_column(
        "events",
        "value_cr",
        type_=sa.Numeric(precision=14, scale=2),
        existing_type=sa.Numeric(precision=16, scale=4),
    )
