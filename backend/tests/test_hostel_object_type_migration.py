import os
import tempfile
import unittest
from unittest.mock import patch

from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError

from alembic import command


class HostelObjectTypeMigrationTest(unittest.TestCase):
    def test_upgrade_preserves_objects_and_allows_only_the_new_hostel_type(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = os.path.join(temp_dir, "hostel-type.db")
            database_url = f"sqlite:///{database_path}"
            config = Config(
                os.path.join(os.path.dirname(__file__), "..", "alembic.ini")
            )

            with patch.dict(os.environ, {"DATABASE_URL": database_url}, clear=False):
                command.upgrade(config, "f8c1d2e3a409")
                before = create_engine(database_url)
                with before.begin() as connection:
                    connection.execute(
                        text(
                            "INSERT INTO objects "
                            "(id, name, address, type, area_sqm, risk_points, status) "
                            "VALUES (1, 'Существующий офис', 'Бизнес-адрес', "
                            "'office', 10, '[]', 'active')"
                        )
                    )
                    connection.execute(
                        text(
                            "INSERT INTO clients (name, phone, object_id) "
                            "VALUES ('Связанный клиент', NULL, 1)"
                        )
                    )
                before.dispose()

                command.upgrade(config, "head")

            verified = create_engine(database_url)
            try:
                with verified.begin() as connection:
                    self.assertEqual(
                        connection.execute(
                            text("SELECT name FROM objects WHERE id = 1")
                        ).scalar_one(),
                        "Существующий офис",
                    )
                    self.assertEqual(
                        connection.execute(
                            text("SELECT object_id FROM clients")
                        ).scalar_one(),
                        1,
                    )
                    connection.execute(
                        text(
                            "INSERT INTO objects "
                            "(id, name, address, type, area_sqm, risk_points, status) "
                            "VALUES (2, 'Хостел', 'Бизнес-адрес', "
                            "'hostel', 97, '[]', 'active')"
                        )
                    )
                    with self.assertRaises(IntegrityError):
                        connection.execute(
                            text(
                                "INSERT INTO objects "
                                "(id, name, address, type, area_sqm, risk_points, "
                                "status) VALUES (3, 'Склад', 'Бизнес-адрес', "
                                "'warehouse', 20, '[]', 'active')"
                            )
                        )
                    self.assertEqual(
                        list(connection.execute(text("PRAGMA foreign_key_check"))),
                        [],
                    )
                    indexes = {
                        row[1]
                        for row in connection.execute(
                            text("PRAGMA index_list('objects')")
                        )
                    }
                    self.assertIn("uq_objects_contract_id", indexes)
            finally:
                verified.dispose()


if __name__ == "__main__":
    unittest.main()
