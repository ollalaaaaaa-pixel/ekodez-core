import importlib.util
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

MIGRATION_PATH = (
    Path(__file__).parents[1] / "alembic" / "versions" / "e4b7c1d9a205_lead_category.py"
)


class LeadCategoryMigrationTest(unittest.TestCase):
    def test_upgrade_adds_nullable_category_without_backfill(self):
        spec = importlib.util.spec_from_file_location(
            "lead_category_migration", MIGRATION_PATH
        )
        assert spec is not None and spec.loader is not None
        migration: Any = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(migration)

        with TemporaryDirectory() as temp_dir:
            engine = sa.create_engine(f"sqlite:///{Path(temp_dir) / 'test.db'}")
            with engine.begin() as connection:
                connection.exec_driver_sql(
                    "CREATE TABLE leads "
                    "(id INTEGER PRIMARY KEY, source VARCHAR(50) NOT NULL)"
                )
                connection.exec_driver_sql(
                    "INSERT INTO leads (id, source) VALUES (1, 'telegram')"
                )
                context = MigrationContext.configure(connection)
                operations = Operations(context)
                original_op = migration.op
                migration.op = operations
                try:
                    migration.upgrade()
                finally:
                    migration.op = original_op

                columns = {
                    row["name"]: row
                    for row in sa.inspect(connection).get_columns("leads")
                }
                category = connection.exec_driver_sql(
                    "SELECT category FROM leads WHERE id = 1"
                ).scalar_one()

            self.assertIn("category", columns)
            self.assertTrue(columns["category"]["nullable"])
            self.assertIsNone(category)
            engine.dispose()


if __name__ == "__main__":
    unittest.main()
