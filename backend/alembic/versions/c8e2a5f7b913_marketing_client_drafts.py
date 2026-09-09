"""Isolated client Telegram drafts; apply only after SQLite backup."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c8e2a5f7b913"
down_revision: str | None = "b6d9e2f4a711"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "transactions", sa.Column("marketing_source", sa.String(50), nullable=True)
    )
    op.create_table(
        "telegram_client_drafts",
        sa.Column("chat_key", sa.String(64), primary_key=True),
        sa.Column("source", sa.String(50), nullable=False),
        sa.Column("step", sa.String(30), nullable=False),
        sa.Column("encrypted_payload", sa.Text(), nullable=False),
        sa.Column("last_update_id", sa.Integer(), nullable=False),
        sa.Column("last_reply", sa.Text(), nullable=True),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("window_started", sa.DateTime(), nullable=False),
        sa.Column("message_count", sa.Integer(), nullable=False),
        sa.Column("accepted_at", sa.DateTime(), nullable=True),
    )
    op.create_index(
        "ix_telegram_client_drafts_expires_at",
        "telegram_client_drafts",
        ["expires_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_telegram_client_drafts_expires_at",
        table_name="telegram_client_drafts",
    )
    op.drop_table("telegram_client_drafts")
    op.drop_column("transactions", "marketing_source")
