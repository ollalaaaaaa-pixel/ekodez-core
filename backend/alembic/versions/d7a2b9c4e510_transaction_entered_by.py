"""transaction entered_by

Revision ID: d7a2b9c4e510
Revises: f4c1a8b2d901
Create Date: 2026-08-16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d7a2b9c4e510"
down_revision: str | None = "f4c1a8b2d901"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "transactions",
        sa.Column(
            "entered_by",
            sa.String(length=50),
            nullable=False,
            server_default="Артем",
        ),
    )


def downgrade() -> None:
    op.drop_column("transactions", "entered_by")
