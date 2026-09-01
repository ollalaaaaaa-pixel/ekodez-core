import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import date, datetime, timedelta
from decimal import Decimal
from unittest.mock import patch

from alembic.config import Config
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from alembic import command
from app import main
from app.models import Base, Client, Contract, Lead, Object, Treatment
from app.objects import protect_client_pii


class ObjectModelTest(unittest.TestCase):
    def test_object_contract_client_treatment_and_nullable_legacy_lead(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        with Session(engine) as session:
            contract = Contract(
                number="17/08",
                price=Decimal("5000.00"),
                periodicity="monthly",
                service_months=[],
            )
            service_object = Object(
                name="СК Ворон",
                address="П. Галушина 21 к.1",
                type="gym",
                area_sqm=Decimal("200.00"),
                contract=contract,
                risk_points=["раздевалка", "подвал"],
                status="active",
            )
            client = Client(
                name="Артём",
                phone="8921***5000",
                object=service_object,
            )
            treatment = Treatment(
                object=service_object,
                performed_at=datetime(2026, 8, 20, 10, 30),
                performed_by="Артём",
                chemicals_used=[],
            )
            legacy_lead = Lead(source="telegram", status="new")
            session.add_all([client, treatment, legacy_lead])
            session.commit()

            stored_object = session.scalar(select(Object))
            stored_lead = session.scalar(select(Lead))
            assert stored_object is not None and stored_lead is not None
            self.assertEqual(stored_object.area_sqm, Decimal("200.00"))
            self.assertEqual(stored_object.risk_points, ["раздевалка", "подвал"])
            assert stored_object.contract is not None
            self.assertEqual(stored_object.contract.number, "17/08")
            self.assertIsNone(stored_lead.object_id)
        engine.dispose()

    def test_client_requires_object_and_service_masks_personal_data(self):
        key = Fernet.generate_key().decode("ascii")
        with patch.dict(os.environ, {"PII_FERNET_KEY": key}, clear=False):
            protected = protect_client_pii("Котлов Артём Васильевич", "89214725000")
        self.assertEqual(protected["name"], "Артём")
        self.assertEqual(protected["phone"], "8921***5000")
        self.assertIsInstance(protected["encrypted_pii"], str)

        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        with Session(engine) as session:
            session.add(Client(**protected, object_id=None))
            with self.assertRaises(IntegrityError):
                session.commit()
        engine.dispose()


class ObjectApiTest(unittest.TestCase):
    def setUp(self):
        self.original_engine = main.engine
        self.engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        main.engine = self.engine
        self.client = TestClient(main.app, client=("127.0.0.1", 51000))

    def tearDown(self):
        self.client.close()
        main.engine = self.original_engine
        self.engine.dispose()

    def _gym_payload(self, name: str = "СК Ворон") -> dict[str, object]:
        return {
            "name": name,
            "address": "П. Галушина 21 к.1",
            "type": "gym",
            "area_sqm": "200.00",
            "contract": {
                "number": "17/08",
                "price": "5000.00",
                "periodicity": "monthly",
                "service_months": [],
            },
            "risk_points": ["раздевалка", "подвал"],
            "last_treatment_date": "2026-08-01",
            "next_treatment_date": "2026-09-01",
            "status": "active",
        }

    def test_crud_filters_money_strings_and_address_free_log(self):
        output = io.StringIO()
        with redirect_stdout(output):
            created = self.client.post("/api/objects", json=self._gym_payload())

        self.assertEqual(created.status_code, 200)
        body = created.json()
        self.assertEqual(body["name"], "СК Ворон")
        self.assertEqual(body["address"], "П. Галушина 21 к.1")
        self.assertEqual(body["area_sqm"], "200.00")
        self.assertEqual(body["contract"]["price"], "5000.00")
        log = output.getvalue()
        self.assertEqual(json.loads(log)["event"], "object_created")
        self.assertNotIn("Галушина", log)

        listed = self.client.get("/api/objects?type=gym&status=active")
        self.assertEqual(listed.status_code, 200)
        self.assertEqual([row["id"] for row in listed.json()], [body["id"]])

        updated = self.client.patch(
            f"/api/objects/{body['id']}",
            json={"name": "СК Ворон — Архангельск", "status": "warranty"},
        )
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(updated.json()["status"], "warranty")

        deleted = self.client.delete(f"/api/objects/{body['id']}")
        self.assertEqual(deleted.status_code, 204)
        self.assertEqual(self.client.get("/api/objects").json(), [])

    def test_overdue_is_derived_and_filterable_without_persisting_it(self):
        payload = self._gym_payload("Просроченный объект")
        payload["contract"] = None
        payload["next_treatment_date"] = (date.today() - timedelta(days=1)).isoformat()
        created = self.client.post("/api/objects", json=payload)

        self.assertEqual(created.status_code, 200)
        self.assertEqual(created.json()["status"], "overdue")
        self.assertEqual(
            [
                row["name"]
                for row in self.client.get("/api/objects?status=overdue").json()
            ],
            ["Просроченный объект"],
        )
        with Session(self.engine) as session:
            stored = session.scalar(select(Object))
            assert stored is not None
            self.assertEqual(stored.status, "active")

    def test_apartment_address_is_masked_but_local_reveal_can_decrypt_it(self):
        key = Fernet.generate_key().decode("ascii")
        payload = self._gym_payload("Квартира клиента")
        payload.update(
            type="apartment",
            address="г. Архангельск, ул. Ленина, 10, кв. 5",
            contract=None,
        )
        with patch.dict(os.environ, {"PII_FERNET_KEY": key}, clear=False):
            created = self.client.post("/api/objects", json=payload)
            revealed = self.client.get(
                f"/api/objects/{created.json()['id']}?show_pii=true"
            )

        self.assertEqual(created.json()["address"], "г. Архангельск, ***")
        self.assertEqual(
            revealed.json()["address"],
            "г. Архангельск, ул. Ленина, 10, кв. 5",
        )
        self.assertEqual(revealed.headers["cache-control"], "no-store")
        with Session(self.engine) as session:
            stored = session.scalar(select(Object))
            assert stored is not None
            self.assertNotIn("Ленина", stored.address)
            self.assertIsNotNone(stored.encrypted_address)

    def test_apartment_create_and_patch_fail_without_encryption_key(self):
        payload = self._gym_payload("Квартира без ключа")
        payload.update(
            type="apartment",
            address="г. Архангельск, ул. Ленина, 10, кв. 5",
            contract=None,
        )
        with patch.dict(os.environ, {}, clear=True):
            created = self.client.post("/api/objects", json=payload)
        self.assertEqual(created.status_code, 503)
        with Session(self.engine) as session:
            self.assertIsNone(session.scalar(select(Object)))

        key = Fernet.generate_key().decode("ascii")
        with patch.dict(os.environ, {"PII_FERNET_KEY": key}, clear=False):
            created = self.client.post("/api/objects", json=payload)
        with patch.dict(os.environ, {}, clear=True):
            patched = self.client.patch(
                f"/api/objects/{created.json()['id']}",
                json={"address": "г. Архангельск, ул. Воскресенская, 1"},
            )
        self.assertEqual(patched.status_code, 503)
        with patch.dict(os.environ, {"PII_FERNET_KEY": key}, clear=False):
            revealed = self.client.get(
                f"/api/objects/{created.json()['id']}?show_pii=true"
            )
        self.assertIn("Ленина", revealed.json()["address"])

    def test_patch_updates_and_detaches_owned_contract_without_orphans(self):
        created = self.client.post("/api/objects", json=self._gym_payload()).json()
        updated = self.client.patch(
            f"/api/objects/{created['id']}",
            json={
                "contract": {
                    "number": "17/08",
                    "price": "6000.00",
                    "periodicity": "monthly",
                    "service_months": [],
                }
            },
        )
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(updated.json()["contract"]["price"], "6000.00")

        detached = self.client.patch(
            f"/api/objects/{created['id']}", json={"contract": None}
        )
        self.assertEqual(detached.status_code, 200)
        self.assertIsNone(detached.json()["contract"])
        with Session(self.engine) as session:
            self.assertIsNone(session.scalar(select(Contract)))

        recreated = self.client.post(
            "/api/objects", json=self._gym_payload("Новый договор")
        )
        self.assertEqual(recreated.status_code, 200)

    def test_patch_rejects_null_for_required_fields(self):
        object_id = self.client.post("/api/objects", json=self._gym_payload()).json()[
            "id"
        ]
        for field in (
            "name",
            "address",
            "type",
            "area_sqm",
            "risk_points",
            "status",
        ):
            with self.subTest(field=field):
                response = self.client.patch(
                    f"/api/objects/{object_id}", json={field: None}
                )
                self.assertEqual(response.status_code, 422)

    def test_treatment_history_is_newest_first(self):
        with Session(self.engine) as session:
            service_object = Object(
                name="История",
                address="Бизнес-адрес",
                type="office",
                area_sqm=Decimal("50.00"),
                risk_points=[],
                status="active",
            )
            session.add(service_object)
            session.flush()
            session.add_all(
                [
                    Treatment(
                        object_id=service_object.id,
                        performed_at=datetime(2026, 8, 1, 9, 0),
                        performed_by="Артём",
                        chemicals_used=[],
                    ),
                    Treatment(
                        object_id=service_object.id,
                        performed_at=datetime(2026, 8, 20, 11, 0),
                        performed_by="Алексей",
                        chemicals_used=[],
                        notes="Повторная обработка",
                    ),
                ]
            )
            session.commit()
            object_id = service_object.id

        response = self.client.get(f"/api/objects/{object_id}/treatments")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [row["performed_by"] for row in response.json()], ["Алексей", "Артём"]
        )

    def test_invalid_type_and_persisted_overdue_are_rejected(self):
        bad_type = self._gym_payload()
        bad_type["type"] = "warehouse"
        bad_status = self._gym_payload()
        bad_status["status"] = "overdue"

        self.assertEqual(
            self.client.post("/api/objects", json=bad_type).status_code, 422
        )
        self.assertEqual(
            self.client.post("/api/objects", json=bad_status).status_code, 422
        )


class SqliteForeignKeyTest(unittest.TestCase):
    def test_invalid_object_reference_is_rejected(self):
        engine = main.create_app_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        with Session(engine) as session:
            enabled = (
                session.connection().exec_driver_sql("PRAGMA foreign_keys").scalar()
            )
            self.assertEqual(enabled, 1)
            session.add(
                Treatment(
                    object_id=999,
                    performed_at=datetime(2026, 8, 20, 11, 0),
                    performed_by="Артём",
                    chemicals_used=[],
                )
            )
            with self.assertRaises(IntegrityError):
                session.commit()
        engine.dispose()

    def test_constraint_migration_upgrades_populated_sqlite_database(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = os.path.join(temp_dir, "objects.db")
            database_url = f"sqlite:///{database_path}"
            config = Config(
                os.path.join(os.path.dirname(__file__), "..", "alembic.ini")
            )
            with patch.dict(os.environ, {"DATABASE_URL": database_url}, clear=False):
                command.upgrade(config, "c7d4e8f1a205")
                engine = main.create_app_engine(database_url)
                with engine.begin() as connection:
                    connection.exec_driver_sql(
                        "INSERT INTO objects "
                        "(id, name, address, type, area_sqm, risk_points, status) "
                        "VALUES (1, 'Заполненный объект', 'Бизнес-адрес', "
                        "'office', 10, '[]', 'active')"
                    )
                    connection.exec_driver_sql(
                        "INSERT INTO clients (name, phone, object_id) "
                        "VALUES ('Артём', NULL, 1)"
                    )
                engine.dispose()
                command.upgrade(config, "head")

                verified_engine = main.create_app_engine(database_url)
                with Session(verified_engine) as session:
                    self.assertEqual(session.scalar(select(Client.object_id)), 1)
                verified_engine.dispose()


if __name__ == "__main__":
    unittest.main()
