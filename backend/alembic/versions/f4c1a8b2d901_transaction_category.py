"""transaction category

Revision ID: f4c1a8b2d901
Revises: 8167bbea123f
Create Date: 2026-08-16

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "f4c1a8b2d901"
down_revision: str | Sequence[str] | None = "8167bbea123f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "transactions",
        sa.Column("category", sa.String(length=100), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("transactions", "category")
