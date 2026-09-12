import os
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from alembic.config import Config

from alembic import command


class ClientsMigrationTest(unittest.TestCase):
    def test_backup_preserves_source_and_migration_preserves_counts(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "fixture.db"
            with patch.dict(
                os.environ, {"DATABASE_URL": f"sqlite:///{path.as_posix()}"}
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
                    db.commit()
                command.upgrade(config, "d9f3b6a8c014")
                backups = list(Path(folder).glob("*.bak"))
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
