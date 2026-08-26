import os
import tempfile
import unittest
from datetime import date, datetime
from decimal import Decimal
from unittest.mock import patch

from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from alembic import command
from app import main
from app.models import Base, Lead, Object, Transaction


class DashboardApiTest(unittest.TestCase):
    def setUp(self):
        self.original_engine = main.engine
        self.engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        main.engine = self.engine
        self.client = TestClient(main.app)

    def tearDown(self):
        self.client.close()
        main.engine = self.original_engine
        self.engine.dispose()

    def _object(self, name: str) -> Object:
        return Object(
            name=name,
            address="Бизнес-адрес",
            type="office",
            area_sqm=Decimal("10.00"),
            risk_points=[],
            status="active",
        )

    def test_dashboard_metrics_rankings_and_revenue_assignment_invariant(self):
        with Session(self.engine) as session:
            objects = [self._object(name) for name in ("А", "Б", "В", "Г")]
            session.add_all(objects)
            session.flush()
            session.add_all(
                [
                    Transaction(
                        source="manual",
                        operation_date=date(2026, 8, 1),
                        amount=Decimal("400.00"),
                        category="Дезинсекция",
                        kind="income",
                        review_required=False,
                        object_id=objects[0].id,
                    ),
                    Transaction(
                        source="tbank",
                        operation_date=date(2026, 8, 2),
                        amount=Decimal("200.00"),
                        category="Дезинфекция",
                        kind="income",
                        review_required=False,
                        object_id=objects[1].id,
                    ),
                    Transaction(
                        source="tbank",
                        operation_date=date(2026, 8, 2),
                        amount=Decimal("120.00"),
                        category="Дезинсекция",
                        kind="income",
                        review_required=False,
                        object_id=objects[2].id,
                    ),
                    Transaction(
                        source="manual",
                        operation_date=date(2026, 8, 3),
                        amount=Decimal("80.00"),
                        category="Клининг",
                        kind="income",
                        review_required=False,
                        object_id=objects[3].id,
                    ),
                    Transaction(
                        source="tbank",
                        operation_date=date(2026, 8, 2),
                        amount=Decimal("200.00"),
                        category="Другие работы",
                        kind="income",
                        review_required=False,
                    ),
                    Transaction(
                        source="manual",
                        operation_date=date(2026, 8, 2),
                        amount=Decimal("250.00"),
                        category="Материалы и химия",
                        kind="expense",
                        review_required=False,
                    ),
                    Transaction(
                        source="manual",
                        operation_date=date(2026, 7, 31),
                        amount=Decimal("9999.00"),
                        category="Дезинсекция",
                        kind="income",
                        review_required=False,
                    ),
                    Transaction(
                        source="manual",
                        operation_date=date(2026, 8, 2),
                        amount=Decimal("9000.00"),
                        category="Дезинсекция",
                        kind="income",
                        review_required=True,
                    ),
                    Lead(
                        source="telegram",
                        status="done",
                        order_at=datetime(2026, 8, 1, 12, 0),
                    ),
                    Lead(
                        source="telegram",
                        status="new",
                        order_at=datetime(2026, 8, 2, 12, 0),
                    ),
                    Lead(
                        source="telegram",
                        status="done",
                        order_at=datetime(2026, 7, 31, 12, 0),
                    ),
                ]
            )
            session.commit()

        response = self.client.get(
            "/api/analytics/dashboard?start_date=2026-08-01&end_date=2026-08-03"
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["revenue"], "1000.00")
        self.assertEqual(body["expenses"], "250.00")
        self.assertEqual(body["profit"], "750.00")
        self.assertEqual(body["margin_pct"], "75.00")
        self.assertEqual(body["total_leads"], 2)
        self.assertEqual(body["closed_leads"], 1)
        self.assertEqual(body["conversion_rate"], "50.00")
        self.assertEqual(body["average_check"], "1000.00")
        self.assertEqual(body["best_day"], {"date": "2026-08-02", "revenue": "520.00"})
        self.assertEqual(
            body["top_objects"],
            [
                {"object_id": 1, "name": "А", "revenue": "400.00"},
                {"object_id": 2, "name": "Б", "revenue": "200.00"},
                {"object_id": 3, "name": "В", "revenue": "120.00"},
            ],
        )
        self.assertEqual(
            body["top_services"],
            [
                {"category": "Дезинсекция", "revenue": "520.00"},
                {"category": "Дезинфекция", "revenue": "200.00"},
                {"category": "Другие работы", "revenue": "200.00"},
            ],
        )
        self.assertEqual(body["unassigned_revenue"], "200.00")
        linked_revenue = Decimal("800.00")
        self.assertEqual(
            linked_revenue + Decimal(body["unassigned_revenue"]),
            Decimal(body["revenue"]),
        )
        self.assertEqual(
            body["daily"],
            [
                {
                    "date": "2026-08-01",
                    "revenue": "400.00",
                    "expenses": "0.00",
                    "profit": "400.00",
                },
                {
                    "date": "2026-08-02",
                    "revenue": "520.00",
                    "expenses": "250.00",
                    "profit": "270.00",
                },
                {
                    "date": "2026-08-03",
                    "revenue": "80.00",
                    "expenses": "0.00",
                    "profit": "80.00",
                },
            ],
        )

    def test_empty_period_and_bad_range(self):
        empty = self.client.get(
            "/api/analytics/dashboard?start_date=2026-08-01&end_date=2026-08-02"
        )
        self.assertEqual(empty.status_code, 200)
        self.assertEqual(empty.json()["revenue"], "0.00")
        self.assertEqual(empty.json()["margin_pct"], "0.00")
        self.assertEqual(empty.json()["conversion_rate"], "0.00")
        self.assertEqual(empty.json()["average_check"], "0.00")
        self.assertIsNone(empty.json()["best_day"])
        self.assertEqual(empty.json()["top_objects"], [])
        self.assertEqual(empty.json()["daily"], [])

        bad = self.client.get(
            "/api/analytics/dashboard?start_date=2026-08-03&end_date=2026-08-02"
        )
        self.assertEqual(bad.status_code, 422)


class TransactionObjectLinkApiTest(unittest.TestCase):
    def setUp(self):
        self.original_engine = main.engine
        self.engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        main.engine = self.engine
        self.client = TestClient(main.app)
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

    def test_manual_income_accepts_object_and_imported_income_can_be_linked(self):
        created = self.client.post(
            "/api/transactions",
            json={
                "operation_date": "2026-08-26",
                "amount": "5000.00",
                "kind": "income",
                "review_required": False,
                "object_id": self.object_id,
            },
        )
        self.assertEqual(created.status_code, 200)
        self.assertEqual(created.json()["object_id"], self.object_id)
        self.assertEqual(created.json()["object_name"], "СК Ворон")

        day_income = self.client.post(
            "/api/day/entry",
            json={
                "kind": "income",
                "category": "Юридические клиенты",
                "amount": "5000.00",
                "date": "2026-08-26",
                "object_id": self.object_id,
            },
        )
        self.assertEqual(day_income.status_code, 200)
        self.assertEqual(day_income.json()["object_id"], self.object_id)

        with Session(self.engine) as session:
            imported = Transaction(
                source="tbank",
                operation_date=date(2026, 8, 25),
                amount=Decimal("7000.00"),
                category="Юридические клиенты",
                kind="income",
                review_required=False,
            )
            session.add(imported)
            session.commit()
            imported_id = imported.id

        linked = self.client.patch(
            f"/api/transactions/{imported_id}/object",
            json={"object_id": self.object_id},
        )
        self.assertEqual(linked.status_code, 200)
        self.assertEqual(linked.json()["object_name"], "СК Ворон")

        unlinked = self.client.patch(
            f"/api/transactions/{imported_id}/object", json={"object_id": None}
        )
        self.assertEqual(unlinked.status_code, 200)
        self.assertIsNone(unlinked.json()["object_id"])

    def test_link_rejects_expense_and_unknown_object(self):
        with Session(self.engine) as session:
            expense = Transaction(
                source="tbank",
                operation_date=date(2026, 8, 25),
                amount=Decimal("1000.00"),
                category="Прочее",
                kind="expense",
                review_required=False,
            )
            session.add(expense)
            session.commit()
            expense_id = expense.id

        self.assertEqual(
            self.client.patch(
                f"/api/transactions/{expense_id}/object",
                json={"object_id": self.object_id},
            ).status_code,
            422,
        )
        created = self.client.post(
            "/api/transactions",
            json={
                "operation_date": "2026-08-26",
                "amount": "5000.00",
                "kind": "income",
                "object_id": 999,
            },
        )
        self.assertEqual(created.status_code, 404)


class DashboardMigrationTest(unittest.TestCase):
    def test_upgrade_preserves_transaction_and_adds_indexed_nullable_fk(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = os.path.join(temp_dir, "dashboard.db")
            database_url = f"sqlite:///{database_path}"
            config = Config(
                os.path.join(os.path.dirname(__file__), "..", "alembic.ini")
            )
            with patch.dict(os.environ, {"DATABASE_URL": database_url}, clear=False):
                command.upgrade(config, "f2a7c4d8e619")
                engine = main.create_app_engine(database_url)
                with engine.begin() as connection:
                    connection.execute(
                        text(
                            "INSERT INTO transactions "
                            "(source, operation_date, amount, currency, "
                            "entered_by, kind, "
                            "review_required, needs_review, created_at) VALUES "
                            "('manual', '2026-08-26', 5000, 'RUB', 'Артем', "
                            "'income', 0, 0, '2026-08-26 12:00:00')"
                        )
                    )
                engine.dispose()
                command.upgrade(config, "head")

                verified = main.create_app_engine(database_url)
                columns = {
                    column["name"]: column
                    for column in inspect(verified).get_columns("transactions")
                }
                indexes = inspect(verified).get_indexes("transactions")
                foreign_keys = inspect(verified).get_foreign_keys("transactions")
                with verified.connect() as connection:
                    row = connection.execute(
                        text("SELECT amount, object_id FROM transactions")
                    ).one()
                self.assertIn("object_id", columns)
                self.assertTrue(columns["object_id"]["nullable"])
                self.assertIn(
                    ["object_id"], [index["column_names"] for index in indexes]
                )
                self.assertIn(
                    ["object_id"],
                    [
                        foreign_key["constrained_columns"]
                        for foreign_key in foreign_keys
                    ],
                )
                self.assertEqual(row.object_id, None)
                self.assertEqual(Decimal(str(row.amount)), Decimal("5000"))
                verified.dispose()


if __name__ == "__main__":
    unittest.main()
