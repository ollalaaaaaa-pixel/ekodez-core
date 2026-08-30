"""add optional service category to leads

Revision ID: e4b7c1d9a205
Revises: d3a6f8b1c904
Create Date: 2026-08-28 23:40:00
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "e4b7c1d9a205"
down_revision: str | None = "d3a6f8b1c904"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("leads") as batch_op:
        batch_op.add_column(sa.Column("category", sa.String(100), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("leads") as batch_op:
        batch_op.drop_column("category")
