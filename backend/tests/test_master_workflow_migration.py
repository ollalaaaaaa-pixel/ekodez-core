import os
import tempfile
import unittest
from unittest.mock import patch

from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError

from alembic import command


class MasterWorkflowMigrationTest(unittest.TestCase):
    def test_upgrade_preserves_rows_and_enforces_one_income_per_lead(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = os.path.join(temp_dir, "master-workflow.db")
            database_url = f"sqlite:///{database_path}"
            config = Config(
                os.path.join(os.path.dirname(__file__), "..", "alembic.ini")
            )

            with patch.dict(os.environ, {"DATABASE_URL": database_url}, clear=False):
                command.upgrade(config, "e4b7c1d9a205")
                legacy = create_engine(database_url)
                with legacy.begin() as connection:
                    connection.execute(
                        text(
                            "INSERT INTO leads "
                            "(id, source, status, category, created_at) VALUES "
                            "(1, 'telegram', 'new', NULL, '2026-08-30 09:00:00')"
                        )
                    )
                    connection.execute(
                        text(
                            "INSERT INTO transactions "
                            "(id, source, operation_date, amount, currency, kind, "
                            "review_required, needs_review, created_at) VALUES "
                            "(1, 'manual', '2026-08-30', 100, 'RUB', 'income', "
                            "0, 0, '2026-08-30 09:00:00')"
                        )
                    )
                legacy.dispose()

                command.upgrade(config, "head")

            verified = create_engine(database_url)
            try:
                with verified.connect() as connection:
                    lead = connection.execute(
                        text(
                            "SELECT amount, execution_date, performed_by "
                            "FROM leads WHERE id = 1"
                        )
                    ).one()
                    self.assertEqual(str(lead.amount), "0")
                    self.assertIsNone(lead.execution_date)
                    self.assertEqual(lead.performed_by, "Артём")
                    self.assertIsNone(
                        connection.execute(
                            text("SELECT lead_id FROM transactions WHERE id = 1")
                        ).scalar_one()
                    )
                    tables = {
                        row[0]
                        for row in connection.execute(
                            text("SELECT name FROM sqlite_master WHERE type='table'")
                        )
                    }
                    self.assertIn("telegram_master_drafts", tables)
                    transaction_indexes = {
                        row[1]
                        for row in connection.execute(
                            text("PRAGMA index_list('transactions')")
                        )
                    }
                    self.assertIn("uq_transactions_lead_id", transaction_indexes)
                    lead_indexes = {
                        row[1]
                        for row in connection.execute(
                            text("PRAGMA index_list('leads')")
                        )
                    }
                    self.assertIn("ix_leads_execution_date", lead_indexes)
                    self.assertEqual(
                        list(connection.execute(text("PRAGMA foreign_key_check"))),
                        [],
                    )

                with verified.begin() as connection:
                    connection.execute(
                        text(
                            "INSERT INTO transactions "
                            "(source, operation_date, amount, currency, kind, "
                            "review_required, needs_review, lead_id, created_at) "
                            "VALUES "
                            "('lead_auto', '2026-08-31', 2500, 'RUB', 'income', "
                            "0, 0, 1, '2026-08-31 10:01:00')"
                        )
                    )

                with self.assertRaises(IntegrityError), verified.begin() as connection:
                    connection.execute(
                        text(
                            "INSERT INTO transactions "
                            "(source, operation_date, amount, currency, kind, "
                            "review_required, needs_review, lead_id, created_at) "
                            "VALUES ('lead_auto', '2026-08-31', 2500, 'RUB', "
                            "'income', 0, 0, 1, '2026-08-31 10:01:00')"
                        )
                    )

                with verified.begin() as connection:
                    for suffix in (1, 2):
                        connection.execute(
                            text(
                                "INSERT INTO transactions "
                                "(source, operation_date, amount, currency, kind, "
                                "review_required, needs_review, lead_id, created_at) "
                                "VALUES (:source, '2026-08-31', 1, 'RUB', "
                                "'income', 0, 0, NULL, '2026-08-31 11:00:00')"
                            ),
                            {"source": f"nullable-{suffix}"},
                        )
            finally:
                verified.dispose()


if __name__ == "__main__":
    unittest.main()
