"""enforce object ownership constraints

Revision ID: d1e6f9a3b407
Revises: c7d4e8f1a205
Create Date: 2026-08-24 00:10:00
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "d1e6f9a3b407"
down_revision: str | None = "c7d4e8f1a205"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("clients") as batch_op:
        batch_op.alter_column("object_id", existing_type=sa.Integer(), nullable=False)
    op.create_index("uq_objects_contract_id", "objects", ["contract_id"], unique=True)


def downgrade() -> None:
    op.drop_index("uq_objects_contract_id", table_name="objects")
    with op.batch_alter_table("clients") as batch_op:
        batch_op.alter_column("object_id", existing_type=sa.Integer(), nullable=True)
