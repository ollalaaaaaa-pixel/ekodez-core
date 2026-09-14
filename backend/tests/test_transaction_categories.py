import unittest
from datetime import date
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app import main
from app.models import (
    BankCategoryMapping,
    Base,
    Client,
    Object,
    Transaction,
    TransactionCategory,
)


class TransactionCategoryApiTest(unittest.TestCase):
    def setUp(self):
        self.old_engine = main.engine
        self.engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        main.engine = self.engine
        self.client = TestClient(main.app)

    def tearDown(self):
        main.engine = self.old_engine
        self.engine.dispose()

    def test_rename_keeps_bank_mapping_and_soft_delete_keeps_history(self):
        with Session(self.engine) as session:
            category = TransactionCategory(
                title="Материалы и химия", kind="expense", sort_order=0
            )
            session.add(category)
            session.flush()
            category_id = category.id
            session.add(
                BankCategoryMapping(
                    kind="expense", legacy_title=category.title, category_id=category_id
                )
            )
            session.commit()
        url = f"/api/transaction-categories/{category_id}"
        self.assertEqual(
            self.client.patch(
                url, json={"title": "Материалы", "kind": "expense"}
            ).status_code,
            200,
        )
        with Session(self.engine) as session:
            tx = Transaction(
                source="tbank",
                operation_date=date.today(),
                amount=Decimal("12.34"),
                kind="expense",
                category="Материалы и химия",
            )
            session.add(tx)
            session.commit()
            tx_id = tx.id
            self.assertEqual(tx.category_id, category_id)
        self.assertEqual(self.client.delete(url).status_code, 200)
        with Session(self.engine) as session:
            saved = session.get(Transaction, tx_id)
            category_saved = session.get(TransactionCategory, category_id)
            assert saved is not None and category_saved is not None
            self.assertEqual(saved.category_id, category_id)
            self.assertEqual(saved.amount, Decimal("12.34"))
            self.assertFalse(category_saved.is_active)

    def test_tags_partial_patch_and_client_backfill(self):
        with Session(self.engine) as session:
            client = Client(name="TEST", client_type="legal_entity")
            obj = Object(
                name="TEST",
                address="***",
                type="office",
                area_sqm=Decimal("1"),
                client=client,
            )
            session.add(obj)
            session.flush()
            tx = Transaction(
                source="manual",
                operation_date=date.today(),
                amount=Decimal("1.00"),
                kind="income",
                object_id=obj.id,
                tags=["project"],
            )
            session.add(tx)
            session.commit()
            tx_id, client_id = tx.id, client.id
            self.assertEqual(tx.client_id, client_id)
        url = f"/api/transactions/{tx_id}"
        result = self.client.patch(url, json={"description": "test"})
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json()["tags"], ["project"])
        self.assertEqual(result.json()["client_id"], client_id)
        self.assertEqual(self.client.patch(url, json={"tags": None}).status_code, 422)
        self.assertEqual(self.client.patch(url, json={"tags": []}).json()["tags"], [])

    def test_custom_category_is_available_for_day_entry_and_reorder_is_atomic(self):
        row = self.client.post(
            "/api/transaction-categories", json={"title": "Проект", "kind": "income"}
        ).json()
        response = self.client.post(
            "/api/day/entry",
            json={"kind": "income", "category": "Проект", "amount": "10.00"},
        )
        self.assertEqual(response.status_code, 200, response.text)
        bad = self.client.patch(
            "/api/transaction-categories/reorder",
            json=[{"id": row["id"], "sort_order": 8}, {"id": 999, "sort_order": 9}],
        )
        self.assertEqual(bad.status_code, 404)
        self.assertEqual(
            self.client.get("/api/transaction-categories").json()[0]["sort_order"], 0
        )

    def test_reorder_and_soft_delete(self):
        with Session(self.engine) as session:
            session.add_all(
                [
                    TransactionCategory(title="A", kind="expense", sort_order=0),
                    TransactionCategory(title="B", kind="expense", sort_order=1),
                ]
            )
            session.commit()
        rows = self.client.get("/api/transaction-categories?kind=expense").json()
        self.assertEqual(
            self.client.patch(
                "/api/transaction-categories/reorder",
                json={
                    "items": [
                        {"id": rows[0]["id"], "sort_order": 1},
                        {"id": rows[1]["id"], "sort_order": 0},
                    ]
                },
            ).status_code,
            200,
        )
        self.assertEqual(
            self.client.delete(
                f"/api/transaction-categories/{rows[0]['id']}"
            ).status_code,
            200,
        )
        self.assertEqual(
            len(self.client.get("/api/transaction-categories?kind=expense").json()), 1
        )


if __name__ == "__main__":
    unittest.main()
