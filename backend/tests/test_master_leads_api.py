import os
import unittest
from datetime import date
from decimal import Decimal
from unittest.mock import patch

from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app import main
from app.models import Base, Lead, Object, Transaction


class MasterLeadApiTest(unittest.TestCase):
    def setUp(self):
        self.original_engine = main.engine
        self.engine = main.create_app_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        main.engine = self.engine
        self.env = patch.dict(
            os.environ,
            {"PII_FERNET_KEY": Fernet.generate_key().decode("ascii")},
            clear=False,
        )
        self.env.start()
        self.client = TestClient(main.app, client=("127.0.0.1", 51000))
        with Session(self.engine) as session:
            service_object = Object(
                name="ТЕСТ объект",
                address="Бизнес-адрес",
                type="office",
                area_sqm=Decimal("10.00"),
                risk_points=[],
                status="active",
            )
            lead = Lead(
                source="telegram",
                category=None,
                client_name="ТЕСТ",
                phone="8921***5000",
                address="Архангельск, ***",
                status="new",
            )
            session.add_all([service_object, lead])
            session.commit()
            self.object_id = service_object.id
            self.lead_id = lead.id

    def tearDown(self):
        self.client.close()
        self.env.stop()
        main.engine = self.original_engine
        self.engine.dispose()

    def test_patch_updates_operational_fields_and_keeps_pii_masked(self):
        response = self.client.patch(
            f"/api/leads/{self.lead_id}",
            json={
                "amount": "2500.00",
                "execution_date": "2026-08-31",
                "category": "Плесень",
                "object_id": self.object_id,
                "performed_by": "Алексей",
            },
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["amount"], "2500.00")
        self.assertEqual(body["execution_date"], "2026-08-31")
        self.assertEqual(body["category"], "Плесень")
        self.assertEqual(body["object_id"], self.object_id)
        self.assertEqual(body["performed_by"], "Алексей")
        self.assertEqual(body["phone"], "8921***5000")
        self.assertEqual(body["address"], "Архангельск, ***")

    def test_patch_rejects_empty_invalid_values_and_unknown_object(self):
        cases: tuple[tuple[dict[str, object], int], ...] = (
            ({}, 422),
            ({"amount": "1.001"}, 422),
            ({"amount": "-1.00"}, 422),
            ({"category": "Неизвестная"}, 422),
            ({"performed_by": "Иван"}, 422),
            ({"object_id": 99999}, 404),
        )
        for payload, status in cases:
            with self.subTest(payload=payload):
                response = self.client.patch(f"/api/leads/{self.lead_id}", json=payload)
                self.assertEqual(response.status_code, status)

        with Session(self.engine) as session:
            lead = session.get(Lead, self.lead_id)
            assert lead is not None
            self.assertEqual(lead.amount, Decimal("0.00"))
            self.assertIsNone(lead.execution_date)
            self.assertIsNone(lead.category)
            self.assertIsNone(lead.object_id)
            self.assertEqual(lead.performed_by, "Артём")

    def test_ingest_accepts_structured_and_legacy_amount_and_execution_date(self):
        structured = self.client.post(
            "/api/leads/ingest",
            json={
                "text": (
                    "Имя клиента: ТЕСТ Клиент\n"
                    "Телефон: 89214725000\n"
                    "Адрес: Архангельск, ТЕСТ адрес\n"
                    "Сумма: 999,99\n"
                    "Дата и время: 30.08.2026 09:00"
                ),
                "source": "other",
                "category": "Плесень",
                "amount": "2500.00",
                "execution_date": "2026-08-31",
            },
        )
        self.assertEqual(structured.status_code, 200)
        self.assertEqual(structured.json()["amount"], "2500.00")
        self.assertEqual(structured.json()["execution_date"], "2026-08-31")

        legacy = self.client.post(
            "/api/leads/ingest",
            json={
                "text": (
                    "Имя клиента: ТЕСТ Второй\n"
                    "Телефон: 89214725001\n"
                    "Адрес: Архангельск, ТЕСТ второй адрес\n"
                    "Сумма: 2 500,50\n"
                    "Дата и время: 29.08.2026 10:30"
                ),
                "source": "other",
            },
        )
        self.assertEqual(legacy.status_code, 200)
        self.assertEqual(legacy.json()["amount"], "2500.50")
        self.assertEqual(legacy.json()["execution_date"], "2026-08-29")

        malformed = self.client.post(
            "/api/leads/ingest",
            json={"text": "Сумма: не число", "source": "other"},
        )
        self.assertEqual(malformed.status_code, 200)
        self.assertEqual(malformed.json()["amount"], "0.00")

    def test_status_done_creates_idempotent_income_without_inventory(self):
        response = self.client.patch(
            f"/api/leads/{self.lead_id}",
            json={
                "amount": "2500.00",
                "execution_date": "2026-08-31",
                "category": None,
                "object_id": self.object_id,
                "performed_by": "Алексей",
            },
        )
        self.assertEqual(response.status_code, 200)

        for _ in range(2):
            done = self.client.post(
                f"/api/leads/{self.lead_id}/status", json={"status": "done"}
            )
            self.assertEqual(done.status_code, 200)

        with Session(self.engine) as session:
            rows = session.scalars(
                select(Transaction).where(Transaction.lead_id == self.lead_id)
            ).all()
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0].amount, Decimal("2500.00"))
            self.assertEqual(rows[0].operation_date, date(2026, 8, 31))
            self.assertEqual(rows[0].category, "Другие работы")
            self.assertEqual(rows[0].entered_by, "Алексей")

    def test_positive_amount_without_date_does_not_close(self):
        with Session(self.engine) as session:
            lead = session.get(Lead, self.lead_id)
            assert lead is not None
            lead.amount = Decimal("1000.00")
            session.commit()

        response = self.client.post(
            f"/api/leads/{self.lead_id}/status", json={"status": "done"}
        )
        self.assertEqual(response.status_code, 422)
        with Session(self.engine) as session:
            lead = session.get(Lead, self.lead_id)
            assert lead is not None
            self.assertEqual(lead.status, "new")
            self.assertEqual(
                session.scalar(
                    select(func.count())
                    .select_from(Transaction)
                    .where(Transaction.lead_id == self.lead_id)
                ),
                0,
            )


if __name__ == "__main__":
    unittest.main()
