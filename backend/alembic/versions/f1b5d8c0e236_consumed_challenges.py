"""Persist consumed authentication challenge hashes.

Revision ID: f1b5d8c0e236
Revises: e0a4c7b9d125
"""

import sqlalchemy as sa

from alembic import op

revision = "f1b5d8c0e236"
down_revision = "e0a4c7b9d125"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "consumed_challenges",
        sa.Column("challenge_hash", sa.String(64), primary_key=True),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("consumed_challenges")
