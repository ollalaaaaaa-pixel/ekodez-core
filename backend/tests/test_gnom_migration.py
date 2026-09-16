import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.pool import NullPool

from alembic import command


class GnomMigrationTest(unittest.TestCase):
    def test_sqlite_backup_counts_and_income_expense_index(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "data").mkdir()
            url = f"sqlite:///{(root / 'data' / 'test.sqlite').as_posix()}"
            config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
            engine = create_engine(url, poolclass=NullPool)
            with (
                patch.dict(os.environ, {"DATABASE_URL": url}),
                patch("app.migration_backup.BACKUP_ROOT", root / "backups"),
            ):
                command.upgrade(config, "f1b5d8c0e236")
                with engine.begin() as connection:
                    connection.execute(
                        text(
                            "INSERT INTO leads (source, status, created_at) "
                            "VALUES ('other', 'new', '2026-09-01 12:00:00')"
                        )
                    )
                    connection.execute(
                        text(
                            "INSERT INTO transactions (source, operation_date, amount, "
                            "currency, entered_by, kind, review_required, lead_id) "
                            "VALUES ('test', '2026-09-01', 10, 'RUB', "
                            "'test', 'income', 0, 1)"
                        )
                    )
                previous = set((root / "backups").glob("*.bak"))
                command.upgrade(config, "head")
                self.assertEqual(
                    len(set((root / "backups").glob("*.bak")) - previous), 1
                )
                with engine.begin() as connection:
                    self.assertEqual(
                        connection.scalar(text("PRAGMA integrity_check")), "ok"
                    )
                    self.assertEqual(
                        connection.scalar(text("SELECT count(*) FROM leads")), 1
                    )
                    self.assertEqual(
                        connection.scalar(text("SELECT count(*) FROM transactions")), 1
                    )
                    self.assertEqual(
                        connection.scalar(text("SELECT count(*) FROM gnom_records")), 0
                    )
                    self.assertEqual(
                        connection.scalar(
                            text("SELECT version_num FROM alembic_version")
                        ),
                        "f3d7a0b2c458",
                    )
                    connection.execute(
                        text(
                            "INSERT INTO transactions (source, operation_date, amount, "
                            "currency, entered_by, kind, review_required, lead_id) "
                            "VALUES ('test', '2026-09-01', 2, 'RUB', "
                            "'test', 'expense', 0, 1)"
                        )
                    )
                    with self.assertRaises(IntegrityError):
                        connection.execute(
                            text(
                                "INSERT INTO transactions "
                                "(source, operation_date, amount, currency, "
                                "entered_by, kind, review_required, lead_id) "
                                "VALUES ('test', '2026-09-01', 10, 'RUB', "
                                "'test', 'income', 0, 1)"
                            )
                        )
            engine.dispose()
