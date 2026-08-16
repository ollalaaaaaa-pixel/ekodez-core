import unittest
from datetime import date, timedelta
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app import main
from app.models import Base, ExpenseCategory, Transaction


class DayApiTest(unittest.TestCase):
    def setUp(self):
        self.original_engine = main.engine
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        main.engine = self.engine
        with Session(self.engine) as session:
            session.add_all(
                [
                    ExpenseCategory(name="Еда"),
                    ExpenseCategory(name="Аренда склада"),
                ]
            )
            session.commit()

    def tearDown(self):
        main.engine = self.original_engine
        self.engine.dispose()

    def test_create_entry_and_get_day_summary(self):
        target = date(2026, 8, 15)
        income = main.create_day_entry(
            main.DayEntryIn(
                kind="income",
                category="Химчистка",
                amount=Decimal("9000.00"),
                comment="Тургенева 6",
                entered_by="Алексей",
                date=target,
            )
        )
        main.create_day_entry(
            main.DayEntryIn(
                kind="expense",
                category="Еда",
                amount=Decimal("500.00"),
                comment="Обед",
                date=target,
            )
        )

        result = main.get_day(target)

        self.assertEqual(result["income_total"], Decimal("9000.00"))
        self.assertEqual(result["expense_total"], Decimal("500.00"))
        self.assertEqual(result["balance"], Decimal("8500.00"))
        category_totals = {
            (item["kind"], item["category"]): item["total"]
            for item in result["categories"]
        }
        self.assertEqual(category_totals[("income", "Химчистка")], 9000)
        self.assertEqual(category_totals[("expense", "Еда")], 500)
        self.assertEqual(len(result["categories"]), 11)
        self.assertEqual(result["entries"][0]["id"], income.id)
        self.assertEqual(result["entries"][0]["entered_by"], "Алексей")
        self.assertEqual(result["entries"][0]["source"], "manual")
        self.assertFalse(result["entries"][0]["can_delete"])

    def test_review_required_transaction_is_not_in_day_totals(self):
        with Session(self.engine) as session:
            session.add(
                Transaction(
                    source="tg_agent",
                    operation_date=date(2026, 8, 16),
                    amount=Decimal("1000.00"),
                    description="черновик",
                    category="Другие работы",
                    kind="income",
                    review_required=True,
                )
            )
            session.commit()

        result = main.get_day(date(2026, 8, 16))

        self.assertEqual(result["income_total"], 0)
        self.assertEqual(result["entries"], [])

    def test_delete_only_manual_entry_for_today(self):
        today = date.today()
        created = main.create_day_entry(
            main.DayEntryIn(
                kind="expense",
                category="Еда",
                amount=Decimal("500.00"),
                comment="Обед",
                date=today,
            )
        )

        result = main.delete_transaction(created.id)

        self.assertEqual(result, {"status": "deleted", "id": created.id})
        with Session(self.engine) as session:
            self.assertIsNone(session.get(Transaction, created.id))

    def test_delete_rejects_non_manual_or_not_today(self):
        with Session(self.engine) as session:
            session.add_all(
                [
                    Transaction(
                        source="tg_agent",
                        operation_date=date.today(),
                        amount=Decimal("1.00"),
                        category="Прочее",
                        kind="expense",
                        review_required=False,
                    ),
                    Transaction(
                        source="manual",
                        operation_date=date.today() - timedelta(days=1),
                        amount=Decimal("1.00"),
                        category="Прочее",
                        kind="expense",
                        review_required=False,
                    ),
                ]
            )
            session.commit()
            ids = [row.id for row in session.scalars(main.select(Transaction)).all()]

        for tx_id in ids:
            with self.subTest(tx_id=tx_id), self.assertRaises(HTTPException) as ctx:
                main.delete_transaction(tx_id)
            self.assertEqual(ctx.exception.status_code, 403)

    def test_entry_validation_rejects_wrong_category(self):
        with self.assertRaises(HTTPException) as ctx:
            main.create_day_entry(
                main.DayEntryIn(
                    kind="income",
                    category="Еда",
                    amount=Decimal("100.00"),
                    comment="ошибка",
                )
            )

        self.assertEqual(ctx.exception.status_code, 422)

    def test_dynamic_expense_category_is_accepted_and_aggregated(self):
        target = date(2026, 8, 15)
        main.create_day_entry(
            main.DayEntryIn(
                kind="expense",
                category="Аренда склада",
                amount=Decimal("5000.00"),
                comment="Склад",
                date=target,
            )
        )

        result = main.get_day(target)
        totals = {
            (item["kind"], item["category"]): item["total"]
            for item in result["categories"]
        }

        self.assertEqual(totals[("expense", "Аренда склада")], 5000)

    def test_unknown_or_inactive_expense_category_is_rejected(self):
        with Session(self.engine) as session:
            session.add(ExpenseCategory(name="Скрытая", is_active=False))
            session.commit()

        for category in ("Неизвестная", "Скрытая"):
            with self.subTest(category=category):
                with self.assertRaises(HTTPException) as context:
                    main.create_day_entry(
                        main.DayEntryIn(
                            kind="expense",
                            category=category,
                            amount=Decimal("100.00"),
                        )
                    )
                self.assertEqual(context.exception.status_code, 422)

    def test_historical_expense_category_is_not_lost_from_day_totals(self):
        target = date(2026, 8, 14)
        with Session(self.engine) as session:
            session.add(
                Transaction(
                    source="manual",
                    operation_date=target,
                    amount=Decimal("700.00"),
                    category="Старая статья",
                    kind="expense",
                    review_required=False,
                )
            )
            session.commit()

        result = main.get_day(target)
        totals = {
            (item["kind"], item["category"]): item["total"]
            for item in result["categories"]
        }

        self.assertEqual(totals[("expense", "Старая статья")], 700)


if __name__ == "__main__":
    unittest.main()
