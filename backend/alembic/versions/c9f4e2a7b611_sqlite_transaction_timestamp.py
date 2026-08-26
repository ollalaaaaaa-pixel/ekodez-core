"""make the transaction timestamp default SQLite-compatible

Revision ID: c9f4e2a7b611
Revises: b5e1d3f7a824
Create Date: 2026-08-26 21:45:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c9f4e2a7b611"
down_revision: str | None = "b5e1d3f7a824"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _set_created_at_default(default: sa.TextClause) -> None:
    connection = op.get_bind()
    if connection.dialect.name == "sqlite":
        with op.batch_alter_table("transactions", recreate="always") as batch_op:
            batch_op.alter_column(
                "created_at",
                existing_type=sa.DateTime(timezone=True),
                existing_nullable=False,
                server_default=default,
            )
        return

    op.alter_column(
        "transactions",
        "created_at",
        existing_type=sa.DateTime(timezone=True),
        existing_nullable=False,
        server_default=default,
    )


def upgrade() -> None:
    _set_created_at_default(sa.text("CURRENT_TIMESTAMP"))


def downgrade() -> None:
    _set_created_at_default(sa.text("now()"))
