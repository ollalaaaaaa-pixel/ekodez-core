"""Add advertising analytics, attribution and notifications.

Revision ID: a1d5e7c9f302
Revises: f1b5d8c0e236
"""

from pathlib import Path

import sqlalchemy as sa

from alembic import op
from app.migration_backup import backup_sqlite

revision = "a1d5e7c9f302"
down_revision = "f1b5d8c0e236"
branch_labels = None
depends_on = None


def upgrade() -> None:
    connection = op.get_bind()
    preserved_tables = ("leads", "clients", "objects", "transactions")
    before = {
        table: connection.scalar(sa.text(f"SELECT count(*) FROM {table}"))
        for table in preserved_tables
    }
    if connection.dialect.name == "sqlite":
        database = connection.engine.url.database
        if database and database != ":memory:":
            backup_sqlite(Path(database))

    with op.batch_alter_table("leads") as batch_op:
        batch_op.add_column(sa.Column("utm_source", sa.String(100), nullable=True))
        batch_op.add_column(sa.Column("utm_campaign", sa.String(200), nullable=True))
        batch_op.add_column(
            sa.Column("attributed_platform", sa.String(50), nullable=True)
        )
        batch_op.add_column(
            sa.Column("attribution_method", sa.String(20), nullable=True)
        )
        batch_op.add_column(
            sa.Column("attributed_at", sa.DateTime(timezone=True), nullable=True)
        )
        batch_op.create_index(
            "ix_leads_attributed_platform", ["attributed_platform"], unique=False
        )

    op.create_table(
        "ad_spend",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("platform", sa.String(50), nullable=False),
        sa.Column("campaign", sa.String(200), nullable=False),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("spend", sa.Numeric(14, 2), nullable=False),
        sa.Column("impressions", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("clicks", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("conversions", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()
        ),
        sa.CheckConstraint("spend >= 0", name="ck_ad_spend_nonnegative"),
        sa.UniqueConstraint(
            "platform",
            "campaign",
            "period_start",
            "period_end",
            name="uq_ad_spend_platform_campaign_period",
        ),
    )
    op.create_index("ix_ad_spend_platform", "ad_spend", ["platform"])
    op.create_index("ix_ad_spend_period_start", "ad_spend", ["period_start"])

    op.create_table(
        "ad_call_log",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("platform", sa.String(50), nullable=False),
        sa.Column("call_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("phone_hash", sa.String(64), nullable=False),
        sa.Column("source_file", sa.String(255), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now()
        ),
        sa.UniqueConstraint(
            "platform",
            "call_date",
            "phone_hash",
            "source_file",
            name="uq_ad_call_platform_date_hash_file",
        ),
    )
    op.create_index("ix_ad_call_log_platform", "ad_call_log", ["platform"])
    op.create_index("ix_ad_call_log_call_date", "ad_call_log", ["call_date"])
    op.create_index("ix_ad_call_log_phone_hash", "ad_call_log", ["phone_hash"])

    op.create_table(
        "ad_import_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("platform", sa.String(50), nullable=False),
        sa.Column("source_file", sa.String(255), nullable=False),
        sa.Column("file_sha256", sa.String(64), nullable=True),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("rows_imported", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("rows_updated", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("period_start", sa.Date(), nullable=True),
        sa.Column("period_end", sa.Date(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now()
        ),
    )
    op.create_index("ix_ad_import_runs_platform", "ad_import_runs", ["platform"])
    op.create_index("ix_ad_import_runs_status", "ad_import_runs", ["status"])
    op.create_index("ix_ad_import_runs_created_at", "ad_import_runs", ["created_at"])

    op.create_table(
        "notifications",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("kind", sa.String(50), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now()
        ),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "kind IN ('ads_import_ok', 'ads_import_error', "
            "'ads_upload_reminder', 'ads_alert', 'draft_ready')",
            name="ck_notifications_kind",
        ),
    )
    op.create_index("ix_notifications_kind", "notifications", ["kind"])
    op.create_index("ix_notifications_created_at", "notifications", ["created_at"])

    after = {
        table: connection.scalar(sa.text(f"SELECT count(*) FROM {table}"))
        for table in preserved_tables
    }
    if after != before:
        raise RuntimeError("Ads migration: preserved row counts do not match")
    if connection.dialect.name == "sqlite":
        if connection.exec_driver_sql("PRAGMA foreign_key_check").all():
            raise RuntimeError("Ads migration: foreign key violations")
        if connection.exec_driver_sql("PRAGMA integrity_check").scalar() != "ok":
            raise RuntimeError("Ads migration: integrity check failed")


def downgrade() -> None:
    op.drop_table("notifications")
    op.drop_table("ad_import_runs")
    op.drop_table("ad_call_log")
    op.drop_table("ad_spend")
    with op.batch_alter_table("leads") as batch_op:
        batch_op.drop_index("ix_leads_attributed_platform")
        batch_op.drop_column("attributed_at")
        batch_op.drop_column("attribution_method")
        batch_op.drop_column("attributed_platform")
        batch_op.drop_column("utm_campaign")
        batch_op.drop_column("utm_source")
