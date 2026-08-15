"""transaction category

Revision ID: f4c1a8b2d901
Revises: 8167bbea123f
Create Date: 2026-08-16

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "f4c1a8b2d901"
down_revision: Union[str, Sequence[str], None] = "8167bbea123f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "transactions",
        sa.Column("category", sa.String(length=100), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("transactions", "category")
