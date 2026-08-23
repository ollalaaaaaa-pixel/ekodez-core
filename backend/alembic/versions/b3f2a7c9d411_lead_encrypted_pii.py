"""add encrypted PII storage for leads

Revision ID: b3f2a7c9d411
Revises: e9b7c4d2a610
Create Date: 2026-08-23 23:10:00
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b3f2a7c9d411"
down_revision: str | None = "e9b7c4d2a610"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("leads", sa.Column("encrypted_pii", sa.Text(), nullable=True))


def downgrade() -> None:
    raise RuntimeError(
        "Unsafe downgrade blocked: restore the verified pre-PII backup instead"
    )
