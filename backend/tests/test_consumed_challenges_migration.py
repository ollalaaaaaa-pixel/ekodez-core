import importlib.util
import unittest
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError


class ConsumedChallengesMigrationTest(unittest.TestCase):
    def test_sqlite_upgrade_unique_hash_and_downgrade(self):
        path = (
            Path(__file__).parents[1]
            / "alembic/versions/f1b5d8c0e236_consumed_challenges.py"
        )
        spec = importlib.util.spec_from_file_location("challenge_migration", path)
        assert spec is not None and spec.loader is not None
        migration = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(migration)
        self.assertEqual(migration.down_revision, "e0a4c7b9d125")
        engine = create_engine("sqlite:///:memory:")
        with engine.begin() as connection:
            migration.__dict__["op"] = Operations(
                MigrationContext.configure(connection)
            )
            migration.upgrade()
            self.assertEqual(
                {
                    column["name"]
                    for column in inspect(connection).get_columns("consumed_challenges")
                },
                {"challenge_hash", "consumed_at"},
            )
            statement = text("INSERT INTO consumed_challenges VALUES (:hash, :at)")
            values = {"hash": "a" * 64, "at": "2026-09-14 12:00:00"}
            connection.execute(statement, values)
            with self.assertRaises(IntegrityError):
                connection.execute(statement, values)
            self.assertEqual(
                connection.scalar(text("SELECT count(*) FROM consumed_challenges")), 1
            )
            self.assertEqual(connection.scalar(text("PRAGMA integrity_check")), "ok")
            migration.downgrade()
            self.assertNotIn(
                "consumed_challenges", inspect(connection).get_table_names()
            )
        engine.dispose()
