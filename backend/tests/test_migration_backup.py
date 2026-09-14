import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from app import migration_backup


class MigrationBackupTest(unittest.TestCase):
    def test_snapshot_outside_database_has_verified_logged_hashes(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "database" / "fixture.db"
            source.parent.mkdir()
            with closing(sqlite3.connect(source)) as db:
                db.execute("CREATE TABLE fixture (id INTEGER)")
                db.execute("INSERT INTO fixture VALUES (1)")
                db.commit()
            original_hash = migration_backup.sha256(source)
            with (
                patch.object(migration_backup, "BACKUP_ROOT", root / "backups"),
                self.assertLogs(migration_backup.logger, level="INFO") as logs,
            ):
                backup = migration_backup.backup_sqlite(source)
            self.assertEqual(backup.parent, (root / "backups").resolve())
            self.assertEqual(migration_backup.sha256(source), original_hash)
            self.assertIn(f"source_sha256={original_hash}", logs.output[0])
            self.assertIn(
                f"backup_sha256={migration_backup.sha256(backup)}", logs.output[0]
            )
            self.assertIn("integrity=ok", logs.output[0])
            with closing(sqlite3.connect(backup)) as db:
                self.assertEqual(
                    db.execute("SELECT id FROM fixture").fetchall(), [(1,)]
                )
                self.assertEqual(
                    db.execute("PRAGMA integrity_check").fetchone(), ("ok",)
                )

    def test_rejects_backup_inside_database_directory_or_git(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "database" / "fixture.db"
            repository = root / "repository"
            repository.mkdir()
            (repository / ".git").mkdir()
            for destination in (
                source.parent,
                source.parent / "backups",
                repository / "backups",
            ):
                with (
                    self.subTest(destination=destination),
                    patch.object(migration_backup, "BACKUP_ROOT", destination),
                    self.assertRaisesRegex(RuntimeError, "outside"),
                ):
                    migration_backup.backup_sqlite(source)
