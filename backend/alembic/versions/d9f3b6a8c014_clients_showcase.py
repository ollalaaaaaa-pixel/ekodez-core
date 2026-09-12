"""Independent clients and object ownership with lossless preflight."""

import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

import sqlalchemy as sa

from alembic import op

revision = "d9f3b6a8c014"
down_revision = "c8e2a5f7b913"
branch_labels = None
depends_on = None


def upgrade() -> None:
    connection = op.get_bind()
    pairs = connection.execute(sa.text("SELECT id, object_id FROM clients")).all()
    object_ids = [row.object_id for row in pairs]
    if len(object_ids) != len(set(object_ids)):
        raise RuntimeError(
            "Client migration: multiple clients per object; resolve manually"
        )
    before_objects = connection.scalar(sa.text("SELECT count(*) FROM objects"))
    existing_ids = set(connection.scalars(sa.text("SELECT id FROM objects")))
    if any(object_id not in existing_ids for object_id in object_ids):
        raise RuntimeError("Client migration: orphan client; resolve manually")
    if connection.dialect.name == "sqlite":
        db_path = connection.engine.url.database
        if db_path and db_path != ":memory:":
            source_path = Path(db_path).resolve()
            stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
            backup_path = source_path.with_name(
                f"{source_path.name}.clients-{stamp}.bak"
            )
            with (
                closing(
                    sqlite3.connect(source_path.as_uri() + "?mode=ro", uri=True)
                ) as source,
                closing(sqlite3.connect(backup_path)) as backup,
            ):
                source.backup(backup)
                if backup.execute("PRAGMA integrity_check").fetchone() != ("ok",):
                    raise RuntimeError("Client migration: backup integrity failed")
    # Rebuild clients before objects references it: SQLite foreign_keys stays enabled.
    with op.batch_alter_table("clients") as batch:
        batch.drop_column("object_id")
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
    for client_id, object_id in pairs:
        result = connection.execute(
            sa.text("UPDATE objects SET client_id=:client WHERE id=:object"),
            {"client": client_id, "object": object_id},
        )
        if result.rowcount != 1:
            raise RuntimeError("Client migration: missing object")
    after_clients = connection.scalar(sa.text("SELECT count(*) FROM clients"))
    after_objects = connection.scalar(sa.text("SELECT count(*) FROM objects"))
    links = connection.scalar(
        sa.text("SELECT count(*) FROM objects WHERE client_id IS NOT NULL")
    )
    if (
        after_clients != len(pairs)
        or after_objects != before_objects
        or links != len(pairs)
    ):
        raise RuntimeError("Client migration: row counts do not match")
    if (
        connection.dialect.name == "sqlite"
        and connection.exec_driver_sql("PRAGMA foreign_key_check").all()
    ):
        raise RuntimeError("Client migration: foreign key violations")


def downgrade() -> None:
    raise RuntimeError(
        "Restore verified backup: many-object clients cannot be downgraded losslessly"
    )
