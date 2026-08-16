"""transaction channel

Revision ID: c4e8a1b7d903
Revises: a8f5c3d1e902
Create Date: 2026-08-16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c4e8a1b7d903"
down_revision: str | None = "a8f5c3d1e902"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "transactions",
        sa.Column("channel", sa.String(length=50), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("transactions", "channel")
