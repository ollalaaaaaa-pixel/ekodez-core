"""Independent clients and object ownership with lossless preflight."""

from pathlib import Path

import sqlalchemy as sa

from alembic import op
from app.migration_backup import backup_sqlite

revision = "d9f3b6a8c014"
down_revision = "c8e2a5f7b913"
branch_labels = None
depends_on = None


def upgrade() -> None:
    connection = op.get_bind()
    if connection.dialect.name != "sqlite":
        _upgrade()
        return
    # SQLite cannot rebuild a referenced parent with foreign_keys enabled.
    # Hold a write reservation; roll back the entire schema/data change on error.
    with op.get_context().autocommit_block():
        foreign_keys = connection.exec_driver_sql("PRAGMA foreign_keys").scalar()
        connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
        connection.exec_driver_sql("BEGIN IMMEDIATE")
        try:
            _upgrade()
            connection.exec_driver_sql("COMMIT")
        except BaseException:
            connection.exec_driver_sql("ROLLBACK")
            raise
        finally:
            connection.exec_driver_sql(f"PRAGMA foreign_keys={int(bool(foreign_keys))}")


def _upgrade() -> None:
    connection = op.get_bind()
    pairs = connection.execute(sa.text("SELECT id, object_id FROM clients")).all()
    object_ids = [row.object_id for row in pairs]
    if len(object_ids) != len(set(object_ids)):
        raise RuntimeError(
            "Client migration: multiple clients per object; resolve manually"
        )
    before_objects = connection.scalar(sa.text("SELECT count(*) FROM objects"))
    before_transactions = connection.scalar(
        sa.text("SELECT count(*) FROM transactions")
    )
    existing_ids = set(connection.scalars(sa.text("SELECT id FROM objects")))
    if any(object_id not in existing_ids for object_id in object_ids):
        raise RuntimeError("Client migration: orphan client; resolve manually")
    if connection.dialect.name == "sqlite":
        db_path = connection.engine.url.database
        if db_path and db_path != ":memory:":
            backup_sqlite(Path(db_path))
    if connection.dialect.name == "sqlite":
        connection.exec_driver_sql(
            "ALTER TABLE objects ADD COLUMN client_id INTEGER REFERENCES clients(id)"
        )
    else:
        op.add_column(
            "objects",
            sa.Column(
                "client_id", sa.Integer(), sa.ForeignKey("clients.id"), nullable=True
            ),
        )
    op.create_index("ix_objects_client_id", "objects", ["client_id"])
    if connection.dialect.name == "sqlite":
        connection.exec_driver_sql(
            "ALTER TABLE transactions ADD COLUMN client_id INTEGER "
            "REFERENCES clients(id)"
        )
    else:
        op.add_column(
            "transactions",
            sa.Column(
                "client_id", sa.Integer(), sa.ForeignKey("clients.id"), nullable=True
            ),
        )
    op.create_index("ix_transactions_client_id", "transactions", ["client_id"])
    for client_id, object_id in pairs:
        result = connection.execute(
            sa.text("UPDATE objects SET client_id=:client WHERE id=:object"),
            {"client": client_id, "object": object_id},
        )
        if result.rowcount != 1:
            raise RuntimeError("Client migration: missing object")
        connection.execute(
            sa.text(
                "UPDATE transactions SET client_id=:client WHERE object_id=:object"
            ),
            {"client": client_id, "object": object_id},
        )
    mismatches = connection.scalar(
        sa.text(
            "SELECT count(*) FROM clients c JOIN objects o ON o.id=c.object_id "
            "WHERE o.client_id IS NULL OR o.client_id != c.id"
        )
    )
    transaction_mismatches = connection.scalar(
        sa.text(
            "SELECT count(*) FROM transactions t "
            "JOIN clients c ON c.object_id=t.object_id "
            "WHERE t.client_id IS NULL OR t.client_id != c.id"
        )
    )
    if mismatches or transaction_mismatches:
        raise RuntimeError("Client migration: links mismatch before drop")
    with op.batch_alter_table("clients") as batch:
        batch.drop_column("object_id")
    after_clients = connection.scalar(sa.text("SELECT count(*) FROM clients"))
    after_objects = connection.scalar(sa.text("SELECT count(*) FROM objects"))
    links = connection.scalar(
        sa.text("SELECT count(*) FROM objects WHERE client_id IS NOT NULL")
    )
    if (
        after_clients != len(pairs)
        or after_objects != before_objects
        or links != len(pairs)
        or connection.scalar(sa.text("SELECT count(*) FROM transactions"))
        != before_transactions
    ):
        raise RuntimeError("Client migration: row counts do not match")
    if (
        connection.dialect.name == "sqlite"
        and connection.exec_driver_sql("PRAGMA foreign_key_check").all()
    ):
        raise RuntimeError("Client migration: foreign key violations")
    if (
        connection.dialect.name == "sqlite"
        and connection.exec_driver_sql("PRAGMA integrity_check").scalar() != "ok"
    ):
        raise RuntimeError("Client migration: integrity check failed")


def downgrade() -> None:
    raise RuntimeError(
        "Restore verified backup: many-object clients cannot be downgraded losslessly"
    )
