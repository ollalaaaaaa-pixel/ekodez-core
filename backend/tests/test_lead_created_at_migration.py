import os
import tempfile
import unittest
from datetime import UTC, datetime
from unittest.mock import patch

from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import inspect, select, text
from sqlalchemy.orm import Session

from alembic import command
from app import main
from app.models import Lead


class LeadCreatedAtMigrationTest(unittest.TestCase):
    def test_sqlite_upgrade_keeps_rows_and_ingest_sets_created_at(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = os.path.join(temp_dir, "lead-created-at.db")
            database_url = f"sqlite:///{database_path}"
            config = Config(
                os.path.join(os.path.dirname(__file__), "..", "alembic.ini")
            )

            with patch.dict(os.environ, {"DATABASE_URL": database_url}, clear=False):
                command.upgrade(config, "c9f4e2a7b611")
                legacy_engine = main.create_app_engine(database_url)
                with legacy_engine.begin() as connection:
                    connection.execute(
                        text(
                            "INSERT INTO leads "
                            "(source, external_id, status, created_at) VALUES "
                            "('telegram', 'legacy-test', 'new', "
                            "'2026-08-26 10:00:00')"
                        )
                    )
                    connection.execute(
                        text(
                            "INSERT INTO objects "
                            "(name, address, type, area_sqm, risk_points, status) "
                            "VALUES ('ТЕСТ', 'ТЕСТ', 'office', 10, '[]', 'active')"
                        )
                    )
                    connection.execute(
                        text(
                            "INSERT INTO treatments "
                            "(lead_id, object_id, chemicals_used, performed_at, "
                            "performed_by) VALUES "
                            "(1, 1, '[]', '2026-08-26 10:00:00', 'ТЕСТ')"
                        )
                    )
                legacy_engine.dispose()

                command.upgrade(config, "head")

            engine = main.create_app_engine(database_url)
            original_engine = main.engine
            main.engine = engine
            try:
                client = TestClient(main.app, raise_server_exceptions=False)
                before_ingest = datetime.now(UTC).replace(tzinfo=None)
                with patch.dict(os.environ, {"PII_FERNET_KEY": ""}, clear=False):
                    response = client.post(
                        "/api/leads/ingest",
                        json={
                            "text": (
                                "id сделки: created-at-test\n"
                                "Имя клиента: ТЕСТ\n"
                                "Причина обращения: ТЕСТ"
                            )
                        },
                    )
                after_ingest = datetime.now(UTC).replace(tzinfo=None)
                client.close()

                self.assertEqual(response.status_code, 200, response.text)
                with Session(engine) as session:
                    legacy_row = session.scalar(
                        select(Lead).where(Lead.external_id == "legacy-test")
                    )
                    ingested_row = session.scalar(
                        select(Lead).where(Lead.external_id == "created-at-test")
                    )
                assert legacy_row is not None
                assert ingested_row is not None
                self.assertEqual(str(legacy_row.created_at), "2026-08-26 10:00:00")
                self.assertLessEqual(before_ingest, ingested_row.created_at)
                self.assertLessEqual(ingested_row.created_at, after_ingest)
                with engine.connect() as connection:
                    self.assertEqual(
                        connection.execute(
                            text("SELECT lead_id FROM treatments WHERE id = 1")
                        ).scalar(),
                        1,
                    )

                created_at = next(
                    column
                    for column in inspect(engine).get_columns("leads")
                    if column["name"] == "created_at"
                )
                self.assertIsNone(created_at["default"])
            finally:
                main.engine = original_engine
                engine.dispose()


if __name__ == "__main__":
    unittest.main()
