"""add daily report delivery history and lead closure time

Revision ID: b5e1d3f7a824
Revises: a4d9c2e7f613
Create Date: 2026-08-26 09:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b5e1d3f7a824"
down_revision: str | None = "a4d9c2e7f613"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "leads", sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True)
    )

    op.create_table(
        "sent_reports",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("report_date", sa.Date(), nullable=False),
        sa.Column("report_type", sa.String(length=20), nullable=False),
        sa.Column("recipient_key", sa.String(length=50), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "report_type IN ('auto', 'manual')",
            name="ck_sent_reports_report_type",
        ),
        sa.CheckConstraint(
            "status IN ('sent', 'failed')", name="ck_sent_reports_status"
        ),
    )
    op.create_index("ix_sent_reports_report_date", "sent_reports", ["report_date"])
    op.create_index(
        "uq_sent_reports_successful_auto_recipient_date",
        "sent_reports",
        ["report_date", "recipient_key"],
        unique=True,
        sqlite_where=sa.text("status = 'sent' AND report_type = 'auto'"),
        postgresql_where=sa.text("status = 'sent' AND report_type = 'auto'"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_sent_reports_successful_auto_recipient_date", table_name="sent_reports"
    )
    op.drop_index("ix_sent_reports_report_date", table_name="sent_reports")
    op.drop_table("sent_reports")

    op.drop_column("leads", "closed_at")
