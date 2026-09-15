import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool

from alembic import command
from app.migration_backup import sha256


class ChemicalDictionaryMigrationTest(unittest.TestCase):
    def test_upgrade_backs_up_and_preserves_stock_without_seed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "data").mkdir()
            database = root / "data" / "test.sqlite"
            url = f"sqlite:///{database.as_posix()}"
            config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
            with (
                patch.dict(os.environ, {"DATABASE_URL": url}),
                patch("app.migration_backup.BACKUP_ROOT", root / "backups"),
            ):
                command.upgrade(config, "f1b5d8c0e236")
                engine = create_engine(url, poolclass=NullPool)
                with engine.begin() as connection:
                    connection.execute(
                        text(
                            "INSERT INTO inventory (chemical_name, quantity, "
                            "initial_quantity, unit, batch_number, "
                            "expiry_date, supplier) VALUES "
                            "('ТЕСТ', 7.125, 10, 'л', 'TEST', '2027-01-01', 'ТЕСТ')"
                        )
                    )
                before_hash = sha256(database)
                previous = set((root / "backups").glob("*.bak"))
                with patch("app.migration_backup.logger.info") as log:
                    command.upgrade(config, "head")
                backups = set((root / "backups").glob("*.bak")) - previous
                self.assertEqual(len(backups), 1)
                backup = backups.pop()
                self.assertEqual(log.call_args.args[2], before_hash)
                self.assertEqual(log.call_args.args[3], sha256(backup))
                snapshot = create_engine(
                    f"sqlite:///{backup.as_posix()}", poolclass=NullPool
                )
                with snapshot.connect() as connection:
                    self.assertEqual(
                        connection.scalar(text("PRAGMA integrity_check")), "ok"
                    )
                    self.assertEqual(
                        connection.scalar(text("SELECT quantity FROM inventory")), 7.125
                    )
                    self.assertEqual(
                        connection.scalar(
                            text("SELECT version_num FROM alembic_version")
                        ),
                        "f1b5d8c0e236",
                    )
                snapshot.dispose()
                with engine.connect() as connection:
                    row = connection.execute(
                        text(
                            "SELECT quantity, initial_quantity, active_substance, "
                            "resistance_note, alternatives, dosage_note, "
                            "hazard_class, pest_tags FROM inventory"
                        )
                    ).one()
                    self.assertEqual(
                        tuple(row), (7.125, 10, None, None, "[]", None, None, "[]")
                    )
                    self.assertEqual(
                        connection.scalar(text("PRAGMA integrity_check")), "ok"
                    )
                    self.assertEqual(
                        connection.scalar(
                            text("SELECT version_num FROM alembic_version")
                        ),
                        "f2c6e9a1b347",
                    )
                engine.dispose()
