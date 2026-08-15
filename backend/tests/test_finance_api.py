import unittest
from datetime import date
from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app import main
from app.models import Base, Transaction


class FinanceApiTest(unittest.TestCase):
    def setUp(self):
        self.original_engine = main.engine
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        main.engine = self.engine

    def tearDown(self):
        main.engine = self.original_engine
        self.engine.dispose()

    def transaction_in(self, **overrides):
        values = {
            "operation_date": date(2026, 8, 16),
            "amount": Decimal("100.00"),
            "counterparty": None,
            "description": None,
        }
        values.update(overrides)
        return main.TransactionIn(**values)

    def test_create_transaction_classifies_combined_description_and_counterparty(self):
        row = main.create_transaction(
            self.transaction_in(
                description="Купил химию",
                counterparty="Склад",
            )
        )

        self.assertEqual(row.category, "Материалы")

    def test_create_transaction_uses_other_when_no_rule_matches(self):
        row = main.create_transaction(
            self.transaction_in(description="Обычная операция")
        )

        self.assertEqual(row.category, "Другое")

    def test_classify_recomputes_category_and_updates_optional_amount(self):
        with Session(self.engine) as session:
            row = Transaction(
                source="tg_agent",
                operation_date=date(2026, 8, 16),
                amount=Decimal("0.00"),
                counterparty=None,
                description="оплатил бензин",
                kind="unknown",
                review_required=True,
            )
            session.add(row)
            session.commit()
            tx_id = row.id

        updated = main.classify_transaction(
            tx_id,
            main.ClassifyIn(
                kind="expense",
                review_required=False,
                amount=Decimal("3500.00"),
            ),
        )

        self.assertEqual(updated.kind, "expense")
        self.assertFalse(updated.review_required)
        self.assertEqual(updated.amount, Decimal("3500.00"))
        self.assertEqual(updated.category, "Топливо и машина")


if __name__ == "__main__":
    unittest.main()
