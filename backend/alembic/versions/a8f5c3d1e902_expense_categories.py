"""expense categories

Revision ID: a8f5c3d1e902
Revises: d7a2b9c4e510
Create Date: 2026-08-16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a8f5c3d1e902"
down_revision: str | None = "d7a2b9c4e510"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

INITIAL_EXPENSE_CATEGORIES = (
    "Еда",
    "Топливо и машина",
    "Материалы и химия",
    "Реклама",
    "Оборудование и инструмент",
    "СИЗ",
    "Прочее",
)


def upgrade() -> None:
    op.create_table(
        "expense_categories",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column(
            "is_active",
            sa.Boolean(),
            server_default=sa.true(),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    op.create_index(
        "uq_expense_categories_name_lower",
        "expense_categories",
        [sa.text("lower(btrim(name))")],
        unique=True,
    )
    categories = sa.table(
        "expense_categories",
        sa.column("name", sa.String(length=100)),
    )
    op.bulk_insert(
        categories,
        [{"name": name} for name in INITIAL_EXPENSE_CATEGORIES],
    )


def downgrade() -> None:
    op.drop_index(
        "uq_expense_categories_name_lower",
        table_name="expense_categories",
    )
    op.drop_table("expense_categories")
