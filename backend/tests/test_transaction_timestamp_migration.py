import os
import tempfile
import unittest
from unittest.mock import patch

from alembic.config import Config
from sqlalchemy import inspect, text

from alembic import command
from app import main


class TransactionTimestampMigrationTest(unittest.TestCase):
    def test_sqlite_upgrade_allows_transaction_insert_without_created_at(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = os.path.join(temp_dir, "transaction-timestamp.db")
            database_url = f"sqlite:///{database_path}"
            config = Config(
                os.path.join(os.path.dirname(__file__), "..", "alembic.ini")
            )

            with patch.dict(os.environ, {"DATABASE_URL": database_url}, clear=False):
                command.upgrade(config, "b5e1d3f7a824")

                legacy_engine = main.create_app_engine(database_url)
                with legacy_engine.begin() as connection:
                    connection.execute(
                        text(
                            "INSERT INTO transactions "
                            "(source, operation_date, amount, currency, entered_by, "
                            "kind, review_required, needs_review, created_at) VALUES "
                            "('manual', '2026-08-25', 1000, 'RUB', 'Артем', "
                            "'income', 0, 0, '2026-08-25 10:00:00')"
                        )
                    )
                legacy_engine.dispose()

                command.upgrade(config, "head")

            engine = main.create_app_engine(database_url)
            try:
                with engine.begin() as connection:
                    connection.execute(
                        text(
                            "INSERT INTO transactions "
                            "(source, operation_date, amount, currency, entered_by, "
                            "kind, review_required, needs_review) VALUES "
                            "('manual', '2026-08-26', 2500, 'RUB', 'Алексей', "
                            "'income', 0, 0)"
                        )
                    )

                with engine.connect() as connection:
                    rows = connection.execute(
                        text(
                            "SELECT amount, created_at FROM transactions "
                            "ORDER BY operation_date"
                        )
                    ).all()
                indexes = inspect(engine).get_indexes("transactions")
            finally:
                engine.dispose()

            self.assertEqual([str(row.amount) for row in rows], ["1000", "2500"])
            self.assertEqual(str(rows[0].created_at), "2026-08-25 10:00:00")
            self.assertIsNotNone(rows[1].created_at)
            self.assertIn(["source_hash"], [index["column_names"] for index in indexes])
            self.assertIn(["object_id"], [index["column_names"] for index in indexes])


if __name__ == "__main__":
    unittest.main()
