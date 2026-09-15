"""Owner-maintained chemical dictionary; no product seed."""

from pathlib import Path

import sqlalchemy as sa

from alembic import op
from app.migration_backup import backup_sqlite

revision = "f2c6e9a1b347"
down_revision = "f1b5d8c0e236"
branch_labels = None
depends_on = None


def upgrade() -> None:
    connection = op.get_bind()
    before = connection.scalar(sa.text("SELECT count(*) FROM inventory"))
    if connection.dialect.name == "sqlite":
        database = connection.engine.url.database
        if database and database != ":memory:":
            backup_sqlite(Path(database))
    for column in (
        sa.Column("active_substance", sa.String(300), nullable=True),
        sa.Column("resistance_note", sa.Text(), nullable=True),
        sa.Column("alternatives", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("dosage_note", sa.Text(), nullable=True),
        sa.Column("hazard_class", sa.String(100), nullable=True),
        sa.Column("pest_tags", sa.JSON(), nullable=False, server_default="[]"),
    ):
        op.add_column("inventory", column)
    if connection.scalar(sa.text("SELECT count(*) FROM inventory")) != before:
        raise RuntimeError("Chemical dictionary migration changed inventory row count")
    if connection.dialect.name == "sqlite":
        if connection.scalar(sa.text("PRAGMA integrity_check")) != "ok":
            raise RuntimeError("Chemical dictionary integrity check failed")


def downgrade() -> None:
    raise RuntimeError("Restore verified backup to preserve chemical dictionary notes")
