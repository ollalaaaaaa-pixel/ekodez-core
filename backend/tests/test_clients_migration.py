import os
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from alembic.config import Config
from sqlalchemy import Engine, event

from alembic import command
from app import migration_backup


class ClientsMigrationTest(unittest.TestCase):
    def test_backup_preserves_source_and_migration_preserves_counts(self):
        self._migration_case()

    def test_drop_failure_rolls_back_schema_and_both_links(self):
        self._migration_case(fail_drop=True)

    def _migration_case(self, fail_drop=False):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "database" / "fixture.db"
            path.parent.mkdir()
            backup_folder = Path(folder) / "backups"
            with (
                patch.dict(
                    os.environ, {"DATABASE_URL": f"sqlite:///{path.as_posix()}"}
                ),
                patch.object(migration_backup, "BACKUP_ROOT", backup_folder),
            ):
                config = Config("alembic.ini")
                command.upgrade(config, "c8e2a5f7b913")
                with closing(sqlite3.connect(path)) as db:
                    db.execute(
                        "INSERT INTO objects "
                        "(id,name,address,type,area_sqm,risk_points,status) "
                        "VALUES (1,'TEST','***','office',10,'[]','active')"
                    )
                    db.execute(
                        "INSERT INTO clients (id,name,object_id) VALUES (7,'TEST',1)"
                    )
                    db.execute(
                        "INSERT INTO transactions (id,source,operation_date,amount,"
                        "currency,kind,category,object_id,review_required) "
                        "VALUES (42,'manual','2026-08-01',12.34,'RUB','expense',"
                        "'Материалы и химия',1,0)"
                    )
                    db.commit()
                drop_seen = []

                def check_before_drop(
                    connection, cursor, statement, parameters, context, executemany
                ):
                    if statement.strip().lower() != "drop table clients":
                        return
                    self.assertEqual(
                        connection.exec_driver_sql(
                            "SELECT client_id FROM objects WHERE id=1"
                        ).scalar(),
                        7,
                    )
                    self.assertEqual(
                        connection.exec_driver_sql(
                            "SELECT client_id FROM transactions WHERE id=42"
                        ).scalar(),
                        7,
                    )
                    self.assertEqual(
                        connection.exec_driver_sql(
                            "SELECT object_id FROM clients WHERE id=7"
                        ).scalar(),
                        1,
                    )
                    drop_seen.append(True)
                    if fail_drop:
                        raise RuntimeError("synthetic drop failure")

                event.listen(Engine, "before_cursor_execute", check_before_drop)
                try:
                    if fail_drop:
                        with self.assertRaisesRegex(
                            RuntimeError, "synthetic drop failure"
                        ):
                            command.upgrade(config, "d9f3b6a8c014")
                    else:
                        command.upgrade(config, "d9f3b6a8c014")
                finally:
                    event.remove(Engine, "before_cursor_execute", check_before_drop)
                self.assertEqual(drop_seen, [True])
                if fail_drop:
                    with closing(sqlite3.connect(path)) as db:
                        self.assertEqual(
                            db.execute("SELECT object_id FROM clients").fetchone(), (1,)
                        )
                        for table in ("objects", "transactions"):
                            self.assertNotIn(
                                "client_id",
                                [
                                    column[1]
                                    for column in db.execute(
                                        f"PRAGMA table_info({table})"
                                    )
                                ],
                            )
                        self.assertEqual(
                            db.execute("PRAGMA integrity_check").fetchone(), ("ok",)
                        )
                        self.assertEqual(
                            db.execute(
                                "SELECT version_num FROM alembic_version"
                            ).fetchone(),
                            ("c8e2a5f7b913",),
                        )
                    return
                backups = list(backup_folder.glob("*.bak"))
                self.assertEqual(len(backups), 1)
                with closing(sqlite3.connect(backups[0])) as old:
                    self.assertEqual(
                        old.execute("SELECT object_id FROM clients").fetchone(), (1,)
                    )
                    self.assertEqual(
                        old.execute("PRAGMA integrity_check").fetchone(), ("ok",)
                    )
                with closing(sqlite3.connect(path)) as db:
                    self.assertEqual(
                        db.execute("SELECT client_id FROM objects").fetchone(), (7,)
                    )
                    self.assertEqual(
                        db.execute("SELECT count(*) FROM clients").fetchone(), (1,)
                    )
                    self.assertEqual(
                        db.execute("PRAGMA foreign_key_check").fetchall(), []
                    )
                    self.assertNotIn(
                        "object_id",
                        [row[1] for row in db.execute("PRAGMA table_info(clients)")],
                    )
                    self.assertEqual(
                        db.execute(
                            "SELECT client_id FROM transactions WHERE id=42"
                        ).fetchone(),
                        (7,),
                    )
                command.upgrade(config, "e0a4c7b9d125")
                with closing(sqlite3.connect(path)) as db:
                    mapping = db.execute(
                        "SELECT category_id FROM bank_category_mappings "
                        "WHERE kind='expense' AND legacy_title='Материалы и химия'"
                    ).fetchone()[0]
                    self.assertEqual(
                        db.execute(
                            "SELECT client_id, category_id, tags, amount "
                            "FROM transactions WHERE id=42"
                        ).fetchone(),
                        (7, mapping, "[]", 12.34),
                    )
                    mismatches = db.execute(
                        "SELECT count(*) FROM bank_category_mappings m "
                        "JOIN transaction_categories c ON c.id=m.category_id "
                        "WHERE m.kind != c.kind OR m.legacy_title != c.title"
                    ).fetchone()[0]
                    self.assertEqual(mismatches, 0)
                    self.assertEqual(
                        db.execute("PRAGMA foreign_key_check").fetchall(), []
                    )
