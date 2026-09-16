"""Gnom encrypted history, staging and import control."""

from pathlib import Path

import sqlalchemy as sa

from alembic import op
from app.migration_backup import backup_sqlite

revision = "f3d7a0b2c458"
down_revision = "a1d5e7c9f302"
branch_labels = None
depends_on = None


def upgrade() -> None:
    connection = op.get_bind()
    if connection.dialect.name != "sqlite":
        _upgrade()
        return
    with op.get_context().autocommit_block():
        foreign_keys = connection.exec_driver_sql("PRAGMA foreign_keys").scalar()
        connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
        connection.exec_driver_sql("BEGIN IMMEDIATE")
        try:
            _upgrade()
            if connection.exec_driver_sql("PRAGMA foreign_key_check").fetchone():
                raise RuntimeError("Gnom migration foreign key check failed")
            connection.exec_driver_sql("COMMIT")
        except BaseException:
            connection.exec_driver_sql("ROLLBACK")
            raise
        finally:
            connection.exec_driver_sql(f"PRAGMA foreign_keys={int(bool(foreign_keys))}")


def _upgrade() -> None:
    connection = op.get_bind()
    before = {
        name: connection.scalar(sa.text(f"SELECT count(*) FROM {name}"))
        for name in ("clients", "objects", "leads", "transactions")
    }
    if connection.dialect.name == "sqlite":
        database = connection.engine.url.database
        if database and database != ":memory:":
            backup_sqlite(Path(database))
    op.add_column(
        "leads",
        sa.Column("is_repeat", sa.Boolean(), nullable=False, server_default="0"),
    )
    allowed = "performed_by IN ('Артём', 'Алексей', 'Не указан (история)')"
    if connection.dialect.name == "sqlite":
        for suffix, event in (
            ("insert", "INSERT"),
            ("update", "UPDATE OF performed_by"),
        ):
            op.execute(f"DROP TRIGGER IF EXISTS ck_leads_performed_by_{suffix}")
            op.execute(
                f"CREATE TRIGGER ck_leads_performed_by_{suffix} "
                f"BEFORE {event} ON leads WHEN NOT (NEW.{allowed}) "
                "BEGIN SELECT RAISE(ABORT, 'ck_leads_performed_by'); END"
            )
    else:
        with op.batch_alter_table("leads") as batch:
            batch.drop_constraint("ck_leads_performed_by", type_="check")
            batch.create_check_constraint("ck_leads_performed_by", allowed)
    op.drop_index("uq_transactions_lead_id", table_name="transactions")
    op.create_index(
        "uq_transactions_lead_id",
        "transactions",
        ["lead_id"],
        unique=True,
        sqlite_where=sa.text("kind = 'income'"),
        postgresql_where=sa.text("kind = 'income'"),
    )
    op.create_table(
        "gnom_records",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("signature", sa.String(64), nullable=False, unique=True),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("phone_hash", sa.String(64), nullable=False),
        sa.Column("phone_hashes", sa.JSON(), nullable=False),
        sa.Column("address_hash", sa.String(64), nullable=False),
        sa.Column(
            "lead_id",
            sa.Integer(),
            sa.ForeignKey("leads.id"),
            nullable=False,
            unique=True,
        ),
        sa.Column(
            "object_id", sa.Integer(), sa.ForeignKey("objects.id"), nullable=False
        ),
        sa.Column(
            "client_id", sa.Integer(), sa.ForeignKey("clients.id"), nullable=False
        ),
        sa.Column("treatment_id", sa.Integer(), sa.ForeignKey("treatments.id")),
        sa.Column("income_id", sa.Integer(), sa.ForeignKey("transactions.id")),
        sa.Column("expense_id", sa.Integer(), sa.ForeignKey("transactions.id")),
        sa.Column("signals", sa.JSON(), nullable=False),
        sa.Column("source", sa.String(30), nullable=False),
        sa.Column("deal_id", sa.String(100)),
        sa.Column("platform", sa.String(100)),
        sa.Column("income", sa.Numeric(14, 2), nullable=False),
        sa.Column("outcome", sa.Numeric(14, 2), nullable=False),
        sa.Column("expense_confirmed", sa.Boolean(), nullable=False),
        sa.Column("start", sa.DateTime(), nullable=False),
        sa.Column("created", sa.DateTime()),
        sa.Column("finished", sa.Boolean(), nullable=False),
        sa.Column("cancelled", sa.Boolean(), nullable=False),
    )
    for column in ("phone_hash", "address_hash", "deal_id", "start"):
        op.create_index(f"ix_gnom_records_{column}", "gnom_records", [column])
    op.create_table(
        "gnom_import_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("filename", sa.String(200), nullable=False),
        sa.Column("file_hash", sa.String(64), nullable=False),
        sa.Column("rows", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("error", sa.String(200)),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_gnom_import_runs_file_hash", "gnom_import_runs", ["file_hash"])
    op.create_table(
        "gnom_settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("weekly_enabled", sa.Boolean(), nullable=False),
        sa.Column("warranty_days", sa.Integer()),
    )
    op.create_table(
        "gnom_platform_rules",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("deal_prefix", sa.String(100), unique=True, nullable=False),
        sa.Column("platform", sa.String(100), nullable=False),
    )
    op.create_table(
        "gnom_candidates",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("fingerprint", sa.String(64), unique=True, nullable=False),
        sa.Column("kind", sa.String(30), nullable=False),
        sa.Column("encrypted_value", sa.Text(), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("inventory_id", sa.Integer(), sa.ForeignKey("inventory.id")),
    )
    op.create_table(
        "gnom_weekly_runs",
        sa.Column("week", sa.Date(), primary_key=True),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=False),
    )
    for name, count in before.items():
        if connection.scalar(sa.text(f"SELECT count(*) FROM {name}")) != count:
            raise RuntimeError("Gnom migration row count mismatch")
    if (
        connection.dialect.name == "sqlite"
        and connection.scalar(sa.text("PRAGMA integrity_check")) != "ok"
    ):
        raise RuntimeError("Gnom migration integrity check failed")


def downgrade() -> None:
    raise RuntimeError("Restore verified backup to preserve Gnom history")
