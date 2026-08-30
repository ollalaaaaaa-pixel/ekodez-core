import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app import main, tg_poller
from app.models import Base, Lead
from app.security.migrate_lead_pii import load_pii_environment, migrate_sqlite_database

LEAD_TEXT = (
    "id сделки: 700001\n"
    "Имя клиента: Котлов Артём Васильевич\n"
    "Телефон: 89214725000\n"
    "Адрес: г. Архангельск, ул. Ленина, 10, кв. 5\n"
    "Причина обращения: тараканы\n"
    "Комментарий: запасной телефон +7 (911) 222-33-44, адрес ул. Поморская 5"
)


class LeadPiiApiTest(unittest.TestCase):
    def setUp(self):
        self.original_engine = main.engine
        self.engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        main.engine = self.engine

    def tearDown(self):
        main.engine = self.original_engine
        self.engine.dispose()

    def test_ingest_without_key_stores_only_masks_and_health_is_degraded(self):
        with patch.dict(os.environ, {}, clear=True):
            result = main.ingest_lead(main.RawTextIn(text=LEAD_TEXT))

            with Session(self.engine) as session:
                row = session.scalar(select(Lead))
                assert row is not None
                self.assertEqual(row.client_name, "Артём")
                self.assertEqual(row.phone, "8921***5000")
                self.assertEqual(row.address, "г. Архангельск, ***")
                self.assertIsNone(row.encrypted_pii)
                self.assertNotIn("Ленина", row.raw_text or "")
                self.assertNotIn("222-33-44", row.raw_text or "")
                self.assertEqual(row.comment, "***")

            self.assertEqual(result.phone, "8921***5000")
            self.assertEqual(main.health()["pii"], "degraded")

    def test_manual_ingest_accepts_aggregators_and_mold_category(self):
        with patch.dict(os.environ, {}, clear=True):
            result = main.ingest_lead(
                main.RawTextIn(
                    text=LEAD_TEXT.replace("700001", "700002"),
                    source="aggregators",
                    category="Плесень",
                )
            )

        self.assertEqual(result.source, "aggregators")
        self.assertEqual(result.category, "Плесень")
        self.assertEqual(result.phone, "8921***5000")
        with Session(self.engine) as session:
            row = session.scalar(select(Lead).where(Lead.external_id == "700002"))
            assert row is not None
            self.assertEqual(row.source, "aggregators")
            self.assertEqual(row.category, "Плесень")

    def test_manual_ingest_rejects_unknown_source_or_category(self):
        client = TestClient(main.app)
        for payload in (
            {"text": LEAD_TEXT, "source": "unknown", "category": "Плесень"},
            {"text": LEAD_TEXT, "source": "aggregators", "category": "Чужая"},
        ):
            with self.subTest(payload=payload):
                response = client.post("/api/leads/ingest", json=payload)
                self.assertEqual(response.status_code, 422)
        client.close()

    def test_localhost_can_reveal_encrypted_pii_and_audit_has_no_pii(self):
        key = Fernet.generate_key().decode("ascii")
        output = io.StringIO()
        with patch.dict(os.environ, {"PII_FERNET_KEY": key}, clear=False):
            main.ingest_lead(main.RawTextIn(text=LEAD_TEXT))
            client = TestClient(
                main.app,
                client=("127.0.0.1", 50000),
            )
            with redirect_stdout(output):
                response = client.get("/api/leads/1?show_pii=true")
            client.close()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["phone"], "89214725000")
        self.assertEqual(
            response.json()["comment"],
            "запасной телефон +7 (911) 222-33-44, адрес ул. Поморская 5",
        )
        self.assertEqual(response.headers["cache-control"], "no-store")
        self.assertEqual(
            response.json()["address"],
            "г. Архангельск, ул. Ленина, 10, кв. 5",
        )
        audit = output.getvalue()
        self.assertIn('"event": "pii_revealed"', audit)
        self.assertIn('"lead_id": 1', audit)
        self.assertNotIn("89214725000", audit)
        self.assertNotIn("Ленина", audit)

    def test_non_local_client_cannot_reveal_even_with_forwarded_header(self):
        key = Fernet.generate_key().decode("ascii")
        with patch.dict(os.environ, {"PII_FERNET_KEY": key}, clear=False):
            main.ingest_lead(main.RawTextIn(text=LEAD_TEXT))
            client = TestClient(main.app, client=("10.0.0.8", 50000))
            response = client.get(
                "/api/leads/1?show_pii=true",
                headers={"X-Forwarded-For": "127.0.0.1"},
            )
            client.close()

        self.assertEqual(response.status_code, 403)
        self.assertNotIn("89214725000", response.text)

    def test_telegram_ingest_masks_database_and_confirmation(self):
        key = Fernet.generate_key().decode("ascii")
        with patch.dict(os.environ, {"PII_FERNET_KEY": key}, clear=False):
            result = tg_poller._ingest(self.engine, LEAD_TEXT)

        self.assertEqual(result, "created")
        with Session(self.engine) as session:
            row = session.scalar(select(Lead))
            assert row is not None
            self.assertEqual(row.phone, "8921***5000")
            self.assertNotIn("Ленина", row.raw_text or "")
            self.assertIsNotNone(row.encrypted_pii)

    def test_structured_ingest_log_contains_no_personal_data(self):
        output = io.StringIO()
        with patch.dict(os.environ, {}, clear=True), redirect_stdout(output):
            tg_poller._ingest(self.engine, LEAD_TEXT)

        log_line = output.getvalue()
        parsed = json.loads(log_line)
        self.assertEqual(parsed["event"], "lead_ingested")
        self.assertEqual(parsed["external_id"], "700001")
        self.assertNotIn("Котлов", log_line)
        self.assertNotIn("89214725000", log_line)
        self.assertNotIn("Ленина", log_line)

    def test_legacy_migration_creates_backup_before_masking_rows(self):
        key = Fernet.generate_key().decode("ascii")
        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = os.path.join(temp_dir, "ekodez.db")
            backup_dir = os.path.join(temp_dir, "backups")
            engine = create_engine(f"sqlite:///{database_path}")
            Base.metadata.create_all(engine)
            with Session(engine) as session:
                session.add(
                    Lead(
                        source="telegram",
                        client_name="Котлов Артём Васильевич",
                        phone="89214725000",
                        address="г. Архангельск, ул. Ленина, 10",
                        raw_text=LEAD_TEXT,
                        status="new",
                    )
                )
                session.commit()
            engine.dispose()

            with patch.dict(os.environ, {"PII_FERNET_KEY": key}, clear=False):
                result = migrate_sqlite_database(database_path, backup_dir)

            self.assertEqual(result.migrated_count, 1)
            self.assertTrue(os.path.isfile(result.backup_path))
            self.assertIn("pre-pii-backup", os.path.basename(result.backup_path))
            backup_engine = create_engine(f"sqlite:///{result.backup_path}")
            with Session(backup_engine) as session:
                backup_row = session.scalar(select(Lead))
                assert backup_row is not None
                self.assertEqual(backup_row.phone, "89214725000")
            backup_engine.dispose()
            migrated_engine = create_engine(f"sqlite:///{database_path}")
            with Session(migrated_engine) as session:
                row = session.scalar(select(Lead))
                assert row is not None
                self.assertEqual(row.phone, "8921***5000")
                self.assertIsNotNone(row.encrypted_pii)
            migrated_engine.dispose()

    def test_migration_cli_loads_key_from_explicit_env_file(self):
        key = Fernet.generate_key().decode("ascii")
        with tempfile.TemporaryDirectory() as temp_dir:
            env_path = os.path.join(temp_dir, ".env")
            with open(env_path, "w", encoding="utf-8") as env_file:
                env_file.write(f"PII_FERNET_KEY={key}\n")
            with patch.dict(os.environ, {}, clear=True):
                load_pii_environment(env_path)
                self.assertEqual(os.environ["PII_FERNET_KEY"], key)


if __name__ == "__main__":
    unittest.main()
