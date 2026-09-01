import os
import tempfile
import unittest
from unittest.mock import patch

from alembic.config import Config
from sqlalchemy import create_engine, text

from alembic import command


class ContractsAndActsMigrationTest(unittest.TestCase):
    def test_upgrade_preserves_price_and_adds_contract_period_tables(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = os.path.join(temp_dir, "contracts-and-acts.db")
            database_url = f"sqlite:///{database_path}"
            config = Config(
                os.path.join(os.path.dirname(__file__), "..", "alembic.ini")
            )

            with patch.dict(os.environ, {"DATABASE_URL": database_url}, clear=False):
                command.upgrade(config, "f6a8c2d4e701")
                legacy = create_engine(database_url)
                with legacy.begin() as connection:
                    connection.execute(
                        text(
                            "INSERT INTO contracts "
                            "(id, number, monthly_amount, start_date) "
                            "VALUES (1, '17/08', 5000.00, '2026-08-17')"
                        )
                    )
                    connection.execute(
                        text(
                            "INSERT INTO objects "
                            "(id, name, address, type, area_sqm, contract_id, "
                            "risk_points, status) VALUES "
                            "(1, 'СК Ворон', 'Бизнес-адрес', 'gym', 200, 1, "
                            "'[]', 'active')"
                        )
                    )
                legacy.dispose()

                command.upgrade(config, "head")

            verified = create_engine(database_url)
            try:
                with verified.connect() as connection:
                    contract = connection.execute(
                        text(
                            "SELECT price, contract_date, periodicity, service_months, "
                            "payment_term_business_days, default_ksp, "
                            "default_derat_glue, default_baits, "
                            "default_disinsection_glue "
                            "FROM contracts WHERE id = 1"
                        )
                    ).one()
                    self.assertEqual(str(contract.price), "5000")
                    self.assertIsNone(contract.contract_date)
                    self.assertIsNone(contract.periodicity)
                    self.assertIn(contract.service_months, (None, "[]"))
                    self.assertEqual(contract.payment_term_business_days, 5)
                    self.assertEqual(contract.default_ksp, 5)
                    self.assertEqual(contract.default_derat_glue, 5)
                    self.assertEqual(contract.default_baits, 5)
                    self.assertEqual(contract.default_disinsection_glue, 6)

                    tables = {
                        row[0]
                        for row in connection.execute(
                            text("SELECT name FROM sqlite_master WHERE type='table'")
                        )
                    }
                    self.assertIn("inspection_reports", tables)
                    self.assertIn("contract_periods", tables)
                    self.assertEqual(
                        list(connection.execute(text("PRAGMA foreign_key_check"))), []
                    )

                    inspection_columns = {
                        row[1]
                        for row in connection.execute(
                            text("PRAGMA table_info('inspection_reports')")
                        )
                    }
                    self.assertIn("control_date", inspection_columns)

                    period_columns = {
                        row[1]
                        for row in connection.execute(
                            text("PRAGMA table_info('contract_periods')")
                        )
                    }
                    self.assertTrue(
                        {"preparations", "infestation_degree", "extra_services"}
                        <= period_columns
                    )
            finally:
                verified.dispose()


if __name__ == "__main__":
    unittest.main()
