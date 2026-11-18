"""result_filings.prompt_version: which version of the Results reader's instructions read a
filing, so live monitoring can split its rate by prompt version

Revision ID: 0035
Revises: 0034
Create Date: 2026-11-16 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0035"
down_revision: str | None = "0034"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("result_filings", sa.Column("prompt_version", sa.String(16)))


def downgrade() -> None:
    op.drop_column("result_filings", "prompt_version")
