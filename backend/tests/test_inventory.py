import os
import tempfile
import unittest
from datetime import date
from decimal import Decimal
from unittest.mock import patch

from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from alembic import command
from app import main
from app.models import Base, ChemicalUsage, Object, Treatment


class InventoryApiTest(unittest.TestCase):
    def setUp(self):
        self.original_engine = main.engine
        self.engine = main.create_app_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        main.engine = self.engine
        self.client = TestClient(main.app, client=("127.0.0.1", 51000))
        with Session(self.engine) as session:
            service_object = Object(
                name="СК Ворон",
                address="П. Галушина 21 к.1",
                type="gym",
                area_sqm=Decimal("200.00"),
                risk_points=[],
                status="active",
            )
            session.add(service_object)
            session.commit()
            self.object_id = service_object.id

    def tearDown(self):
        self.client.close()
        main.engine = self.original_engine
        self.engine.dispose()

    def _inventory_payload(
        self, chemical_name: str = "Циперметрин", quantity: str = "100.000"
    ) -> dict[str, object]:
        return {
            "chemical_name": chemical_name,
            "quantity": quantity,
            "unit": "мл",
            "batch_number": f"B-{chemical_name}",
            "expiry_date": "2027-08-01",
            "supplier": "Поставщик",
        }

    def test_inventory_crud_filters_decimal_strings_and_low_stock(self):
        created = self.client.post("/api/inventory", json=self._inventory_payload())
        self.assertEqual(created.status_code, 200)
        body = created.json()
        self.assertEqual(body["quantity"], "100.000")
        self.assertEqual(body["initial_quantity"], "100.000")
        self.assertFalse(body["low_stock"])

        filtered = self.client.get(
            "/api/inventory?search=Ципер&supplier=Поставщик&unit=мл"
        )
        self.assertEqual([row["id"] for row in filtered.json()], [body["id"]])

        updated = self.client.patch(
            f"/api/inventory/{body['id']}", json={"quantity": "9.000"}
        )
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(updated.json()["quantity"], "9.000")
        self.assertEqual(updated.json()["initial_quantity"], "100.000")
        self.assertTrue(updated.json()["low_stock"])
        low = self.client.get("/api/inventory?low_stock=true")
        self.assertEqual([row["id"] for row in low.json()], [body["id"]])

        deleted = self.client.delete(f"/api/inventory/{body['id']}")
        self.assertEqual(deleted.status_code, 204)
        self.assertEqual(self.client.get("/api/inventory").json(), [])

    def test_duplicate_batch_is_rejected(self):
        payload = self._inventory_payload()
        self.assertEqual(
            self.client.post("/api/inventory", json=payload).status_code, 200
        )
        duplicate = self.client.post("/api/inventory", json=payload)
        self.assertEqual(duplicate.status_code, 409)

    def test_treatment_atomically_decrements_inventory_and_records_usage(self):
        first = self.client.post(
            "/api/inventory", json=self._inventory_payload()
        ).json()
        second = self.client.post(
            "/api/inventory",
            json=self._inventory_payload("ДезХлор", "50.000"),
        ).json()

        response = self.client.post(
            "/api/treatments",
            json={
                "object_id": self.object_id,
                "performed_at": "2026-08-26T12:30:00",
                "performed_by": "Артём",
                "notes": "Профилактика",
                "chemicals_used": [
                    {"inventory_id": first["id"], "quantity_used": "1.250"},
                    {"inventory_id": second["id"], "quantity_used": "5.000"},
                ],
            },
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(
            [row["quantity_used"] for row in body["chemicals_used"]],
            ["1.250", "5.000"],
        )
        self.assertEqual(
            [row["chemical_name"] for row in body["chemicals_used"]],
            ["Циперметрин", "ДезХлор"],
        )
        inventory = self.client.get("/api/inventory").json()
        quantities = {row["chemical_name"]: row["quantity"] for row in inventory}
        self.assertEqual(quantities, {"Циперметрин": "98.750", "ДезХлор": "45.000"})

        with Session(self.engine) as session:
            usages = session.scalars(
                select(ChemicalUsage).order_by(ChemicalUsage.id)
            ).all()
            treatment = session.get(Treatment, body["id"])
            service_object = session.get(Object, self.object_id)
            self.assertEqual(
                [row.quantity for row in usages], [Decimal("1.250"), Decimal("5.000")]
            )
            assert treatment is not None and service_object is not None
            self.assertEqual(treatment.chemicals_used[0]["quantity_used"], "1.250")
            self.assertEqual(service_object.last_treatment_date, date(2026, 8, 26))

        history = self.client.get("/api/treatments")
        self.assertEqual(history.status_code, 200)
        self.assertEqual(history.json()[0]["notes"], "Профилактика")

    def test_insufficient_stock_rolls_back_entire_treatment(self):
        first = self.client.post(
            "/api/inventory", json=self._inventory_payload("Первый", "10.000")
        ).json()
        second = self.client.post(
            "/api/inventory", json=self._inventory_payload("Второй", "2.000")
        ).json()

        response = self.client.post(
            "/api/treatments",
            json={
                "object_id": self.object_id,
                "performed_at": "2026-08-26T12:30:00",
                "performed_by": "Артём",
                "chemicals_used": [
                    {"inventory_id": first["id"], "quantity_used": "3.000"},
                    {"inventory_id": second["id"], "quantity_used": "3.000"},
                ],
            },
        )

        self.assertEqual(response.status_code, 409)
        inventory = self.client.get("/api/inventory").json()
        quantities = {row["chemical_name"]: row["quantity"] for row in inventory}
        self.assertEqual(quantities, {"Первый": "10.000", "Второй": "2.000"})
        with Session(self.engine) as session:
            self.assertIsNone(session.scalar(select(Treatment)))
            self.assertIsNone(session.scalar(select(ChemicalUsage)))

    def test_rejects_duplicate_usage_and_unknown_object(self):
        inventory = self.client.post(
            "/api/inventory", json=self._inventory_payload()
        ).json()
        payload = {
            "object_id": self.object_id,
            "performed_at": "2026-08-26T12:30:00",
            "performed_by": "Артём",
            "chemicals_used": [
                {"inventory_id": inventory["id"], "quantity_used": "1.000"},
                {"inventory_id": inventory["id"], "quantity_used": "2.000"},
            ],
        }
        self.assertEqual(
            self.client.post("/api/treatments", json=payload).status_code, 422
        )
        payload = {
            "object_id": 999,
            "performed_at": date.today().isoformat(),
            "performed_by": "Артём",
            "chemicals_used": [
                {"inventory_id": inventory["id"], "quantity_used": "1.000"}
            ],
        }
        self.assertEqual(
            self.client.post("/api/treatments", json=payload).status_code, 404
        )

    def test_used_inventory_cannot_be_deleted(self):
        inventory = self.client.post(
            "/api/inventory", json=self._inventory_payload()
        ).json()
        treatment = self.client.post(
            "/api/treatments",
            json={
                "object_id": self.object_id,
                "performed_at": "2026-08-26T12:30:00",
                "performed_by": "Артём",
                "chemicals_used": [
                    {"inventory_id": inventory["id"], "quantity_used": "1.000"}
                ],
            },
        )
        self.assertEqual(treatment.status_code, 200)
        self.assertEqual(
            self.client.delete(f"/api/inventory/{inventory['id']}").status_code,
            409,
        )


class InventoryMigrationTest(unittest.TestCase):
    def test_upgrade_preserves_existing_treatment_and_adds_inventory_tables(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = os.path.join(temp_dir, "inventory.db")
            database_url = f"sqlite:///{database_path}"
            config = Config(
                os.path.join(os.path.dirname(__file__), "..", "alembic.ini")
            )
            with patch.dict(os.environ, {"DATABASE_URL": database_url}, clear=False):
                command.upgrade(config, "d1e6f9a3b407")
                engine = main.create_app_engine(database_url)
                with engine.begin() as connection:
                    connection.execute(
                        text(
                            "INSERT INTO objects "
                            "(name, address, type, area_sqm, risk_points, status) "
                            "VALUES ('Объект', 'Бизнес-адрес', 'office', "
                            "10, '[]', 'active')"
                        )
                    )
                    connection.execute(
                        text(
                            "INSERT INTO treatments "
                            "(object_id, chemicals_used, performed_at, performed_by) "
                            "VALUES (1, '[]', '2026-08-20 10:00:00', 'Артём')"
                        )
                    )
                engine.dispose()
                command.upgrade(config, "head")

                verified = main.create_app_engine(database_url)
                with verified.connect() as connection:
                    tables = {
                        row[0]
                        for row in connection.execute(
                            text("SELECT name FROM sqlite_master WHERE type='table'")
                        )
                    }
                    self.assertIn("inventory", tables)
                    self.assertIn("chemical_usage", tables)
                    self.assertEqual(
                        connection.execute(
                            text("SELECT COUNT(*) FROM treatments")
                        ).scalar(),
                        1,
                    )
                verified.dispose()


if __name__ == "__main__":
    unittest.main()
