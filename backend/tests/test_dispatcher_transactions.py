import unittest
from datetime import date, timedelta
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app import main
from app.models import Base, ExpenseCategory, Transaction


class DispatcherTransactionPatchTest(unittest.TestCase):
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

    def _transaction(self, kind: str = "income") -> int:
        with Session(self.engine) as session:
            row = Transaction(
                source="manual",
                operation_date=date.today() - timedelta(days=2),
                amount=Decimal("5000.00"),
                currency="RUB",
                description="Исходный комментарий",
                category="Другие работы" if kind == "income" else "Материалы и химия",
                kind=kind,
                review_required=False,
            )
            session.add(row)
            session.commit()
            return row.id

    def test_patch_updates_date_category_and_description_without_changing_amount(self):
        tx_id = self._transaction()
        new_date = date.today() - timedelta(days=1)

        response = self.client.patch(
            f"/api/transactions/{tx_id}",
            json={
                "operation_date": new_date.isoformat(),
                "category": "Дезинсекция",
                "description": "ТЕСТ-правка",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["operation_date"], new_date.isoformat())
        self.assertEqual(response.json()["category"], "Дезинсекция")
        self.assertEqual(response.json()["description"], "ТЕСТ-правка")
        self.assertEqual(response.json()["amount"], "5000.00")
        with Session(self.engine) as session:
            stored = session.get(Transaction, tx_id)
            self.assertEqual(stored.amount, Decimal("5000.00"))

    def test_patch_rejects_future_date_amount_empty_payload_and_unknown_row(self):
        tx_id = self._transaction()
        future = (date.today() + timedelta(days=1)).isoformat()

        cases = (
            ({"operation_date": future}, 422),
            ({"amount": "1.00"}, 422),
            ({}, 422),
            ({"category": "Материалы и химия"}, 422),
        )
        for payload, expected_status in cases:
            with self.subTest(payload=payload):
                response = self.client.patch(f"/api/transactions/{tx_id}", json=payload)
                self.assertEqual(response.status_code, expected_status)

        missing = self.client.patch(
            "/api/transactions/999999", json={"description": None}
        )
        self.assertEqual(missing.status_code, 404)

    def test_expense_accepts_only_active_expense_category(self):
        tx_id = self._transaction(kind="expense")
        with Session(self.engine) as session:
            session.add(ExpenseCategory(name="Материалы и химия", is_active=True))
            session.add(ExpenseCategory(name="Скрытая категория", is_active=False))
            session.commit()

        accepted = self.client.patch(
            f"/api/transactions/{tx_id}", json={"category": "Материалы и химия"}
        )
        rejected = self.client.patch(
            f"/api/transactions/{tx_id}", json={"category": "Скрытая категория"}
        )

        self.assertEqual(accepted.status_code, 200)
        self.assertEqual(rejected.status_code, 422)


if __name__ == "__main__":
    unittest.main()
