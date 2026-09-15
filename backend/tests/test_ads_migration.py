import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

from alembic import command
from app import migration_backup


class AdsMigrationTest(unittest.TestCase):
    def test_upgrade_preserves_leads_and_adds_ads_schema(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "database" / "ads-migration.db"
            db_path.parent.mkdir()
            database_url = f"sqlite:///{db_path.as_posix()}"
            config = Config(Path(__file__).parents[1] / "alembic.ini")

            backup_root = Path(temp_dir) / "verified-backups"
            with (
                patch.dict(os.environ, {"DATABASE_URL": database_url}, clear=False),
                patch.object(migration_backup, "BACKUP_ROOT", backup_root),
            ):
                command.upgrade(config, "f1b5d8c0e236")
                engine = create_engine(database_url)
                with engine.begin() as connection:
                    connection.execute(
                        text(
                            "INSERT INTO leads "
                            "(source, status, amount, performed_by, created_at) "
                            "VALUES ('telegram', 'new', 0, 'Артём', "
                            "'2026-09-14 10:00:00')"
                        )
                    )
                    before = {
                        table: connection.scalar(text(f"SELECT count(*) FROM {table}"))
                        for table in ("leads", "clients", "objects", "transactions")
                    }
                engine.dispose()

                command.upgrade(config, "head")

            engine = create_engine(database_url)
            try:
                schema = inspect(engine)
                with engine.connect() as connection:
                    lead_count = connection.scalar(text("SELECT count(*) FROM leads"))
                    integrity = connection.scalar(text("PRAGMA integrity_check"))
                    revision_count = connection.scalar(
                        text("SELECT count(*) FROM alembic_version")
                    )
                    after = {
                        table: connection.scalar(text(f"SELECT count(*) FROM {table}"))
                        for table in before
                    }
                    foreign_keys = connection.execute(
                        text("PRAGMA foreign_key_check")
                    ).all()

                self.assertEqual(lead_count, 1)
                self.assertEqual(integrity, "ok")
                self.assertEqual(revision_count, 1)
                self.assertEqual(after, before)
                self.assertEqual(foreign_keys, [])
                backups = list(backup_root.glob("*.bak"))
                self.assertGreaterEqual(len(backups), 2)
                self.assertEqual(len(migration_backup.sha256(backups[-1])), 64)
                self.assertTrue(
                    {"ad_spend", "ad_call_log", "ad_import_runs", "notifications"}
                    <= set(schema.get_table_names())
                )
                lead_columns = {
                    column["name"] for column in schema.get_columns("leads")
                }
                self.assertTrue(
                    {
                        "utm_source",
                        "utm_campaign",
                        "attributed_platform",
                        "attribution_method",
                        "attributed_at",
                    }
                    <= lead_columns
                )
                call_columns = {
                    column["name"] for column in schema.get_columns("ad_call_log")
                }
                self.assertNotIn("phone", call_columns)
                self.assertIn("phone_hash", call_columns)
            finally:
                engine.dispose()


if __name__ == "__main__":
    unittest.main()
