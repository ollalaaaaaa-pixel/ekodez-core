"""T-Bank import audit fields

Revision ID: e9b7c4d2a610
Revises: c4e8a1b7d903
Create Date: 2026-08-16
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "e9b7c4d2a610"
down_revision: str | None = "c4e8a1b7d903"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NEW_EXPENSE_CATEGORIES = ("Налоги и взносы", "Банковские комиссии")


def upgrade() -> None:
    op.add_column(
        "transactions", sa.Column("source_hash", sa.String(64), nullable=True)
    )
    op.add_column("transactions", sa.Column("doc_number", sa.String(50), nullable=True))
    op.add_column(
        "transactions",
        sa.Column("counterparty_inn", sa.String(20), nullable=True),
    )
    op.add_column(
        "transactions", sa.Column("import_batch_id", sa.Uuid(), nullable=True)
    )
    op.add_column(
        "transactions",
        sa.Column("source_filename", sa.String(255), nullable=True),
    )
    op.add_column(
        "transactions",
        sa.Column(
            "needs_review",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_transactions_source_hash",
        "transactions",
        ["source_hash"],
        unique=True,
    )

    category_table = sa.table(
        "expense_categories",
        sa.column("name", sa.String(100)),
        sa.column("is_active", sa.Boolean()),
    )
    connection = op.get_bind()
    for name in NEW_EXPENSE_CATEGORIES:
        exists = connection.scalar(
            sa.select(sa.literal(True)).where(
                sa.exists(
                    sa.select(category_table.c.name).where(
                        category_table.c.name == name
                    )
                )
            )
        )
        if not exists:
            connection.execute(
                category_table.insert().values(name=name, is_active=True)
            )


def downgrade() -> None:
    category_table = sa.table("expense_categories", sa.column("name", sa.String(100)))
    op.get_bind().execute(
        category_table.delete().where(category_table.c.name.in_(NEW_EXPENSE_CATEGORIES))
    )
    op.drop_index("ix_transactions_source_hash", table_name="transactions")
    op.drop_column("transactions", "needs_review")
    op.drop_column("transactions", "source_filename")
    op.drop_column("transactions", "import_batch_id")
    op.drop_column("transactions", "counterparty_inn")
    op.drop_column("transactions", "doc_number")
    op.drop_column("transactions", "source_hash")
