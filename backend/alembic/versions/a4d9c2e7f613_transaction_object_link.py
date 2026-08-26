"""add optional object link to transactions

Revision ID: a4d9c2e7f613
Revises: f2a7c4d8e619
Create Date: 2026-08-26 04:30:00
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a4d9c2e7f613"
down_revision: str | None = "f2a7c4d8e619"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("transactions", recreate="always") as batch_op:
        batch_op.add_column(sa.Column("object_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            "fk_transactions_object_id_objects", "objects", ["object_id"], ["id"]
        )
        batch_op.create_index("ix_transactions_object_id", ["object_id"])


def downgrade() -> None:
    with op.batch_alter_table("transactions", recreate="always") as batch_op:
        batch_op.drop_index("ix_transactions_object_id")
        batch_op.drop_constraint(
            "fk_transactions_object_id_objects", type_="foreignkey"
        )
        batch_op.drop_column("object_id")
