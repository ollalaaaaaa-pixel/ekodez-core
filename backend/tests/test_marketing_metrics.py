import unittest
from datetime import date, datetime
from decimal import Decimal

from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app import main
from app.models import Base, ExpenseCategory, Lead, Transaction


class MarketingMetricsTest(unittest.TestCase):
    def setUp(self):
        self.old = main.engine
        self.engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        main.engine = self.engine
        with Session(self.engine) as s:
            s.add_all([ExpenseCategory(name="Реклама"), ExpenseCategory(name="Прочее")])
            s.commit()

    def tearDown(self):
        main.engine = self.old
        self.engine.dispose()

    def test_tagged_expense_and_confirmed_leads_not_clicks(self):
        from app.marketing_metrics import marketing_metrics

        entry = main.create_day_entry(
            main.DayEntryIn(
                kind="expense",
                category="Реклама",
                amount=Decimal("6000.00"),
                marketing_source="vk",
                date=date(2026, 9, 8),
            )
        )
        with Session(self.engine) as s:
            expense = s.get(Transaction, entry.id)
            assert expense is not None
            self.assertEqual(expense.channel, "ВК")
            s.add(Lead(source="yandex_direct", created_at=datetime(2026, 9, 8, 12)))
            s.commit()
            result = marketing_metrics(s, date(2026, 9, 1), date(2026, 9, 8))
        vk = next(row for row in result["channels"] if row["source"] == "vk")
        self.assertEqual(vk["expenses"], "6000.00")
        self.assertEqual(vk["leads"], 0)
        self.assertIsNone(vk["cpl"])

    def test_utm_maps_only_allowlist(self):
        row = main.ingest_lead(
            main.RawTextIn(text="ТЕСТ", source="other", utm_source="vk")
        )
        self.assertEqual(row.source, "vk")
        row = main.ingest_lead(
            main.RawTextIn(text="ТЕСТ", source="other", utm_source="секрет")
        )
        self.assertEqual(row.source, "other")
        conflict = main.ingest_lead(
            main.RawTextIn(text="ТЕСТ", source="avito", utm_source="vk")
        )
        self.assertEqual(conflict.source, "vk")

    def test_advertising_expense_requires_source_and_can_be_corrected(self):
        with self.assertRaises(HTTPException) as context:
            main.create_day_entry(
                main.DayEntryIn(
                    kind="expense",
                    category="Реклама",
                    amount=Decimal("100.00"),
                    date=date(2026, 9, 8),
                )
            )
        self.assertEqual(context.exception.status_code, 422)

        with Session(self.engine) as session:
            row = Transaction(
                source="manual",
                operation_date=date(2026, 9, 8),
                amount=Decimal("500.00"),
                category="Реклама",
                kind="expense",
                review_required=False,
            )
            session.add(row)
            session.commit()
            row_id = row.id
        updated = main.update_transaction(
            row_id, main.TransactionPatchIn(marketing_source="avito")
        )
        self.assertEqual(updated.marketing_source, "avito")
        self.assertEqual(updated.channel, "Авито")
        with self.assertRaises(HTTPException):
            main.update_transaction(
                row_id, main.TransactionPatchIn(marketing_source=None)
            )
        changed = main.update_transaction(
            row_id, main.TransactionPatchIn(category="Прочее")
        )
        self.assertIsNone(changed.marketing_source)
        self.assertIsNone(changed.channel)

    def test_metrics_use_moscow_boundary_linked_revenue_and_unassigned_spend(self):
        from app.marketing_metrics import marketing_metrics

        with Session(self.engine) as session:
            in_range = Lead(source="vk", created_at=datetime(2026, 8, 31, 21, 0))
            outside = Lead(source="vk", created_at=datetime(2026, 9, 8, 21, 0))
            older_paid = Lead(source="vk", created_at=datetime(2026, 8, 1, 12, 0))
            session.add_all([in_range, outside, older_paid])
            session.flush()
            session.add_all(
                [
                    Transaction(
                        source="manual",
                        operation_date=date(2026, 9, 8),
                        amount=Decimal("6000.00"),
                        category="Реклама",
                        marketing_source="vk",
                        kind="expense",
                        review_required=False,
                    ),
                    Transaction(
                        source="manual",
                        operation_date=date(2026, 9, 8),
                        amount=Decimal("500.00"),
                        category="Реклама",
                        kind="expense",
                        review_required=False,
                    ),
                    Transaction(
                        source="lead_auto",
                        operation_date=date(2026, 9, 8),
                        amount=Decimal("9000.00"),
                        category="Дезинсекция",
                        kind="income",
                        review_required=False,
                        lead_id=older_paid.id,
                    ),
                ]
            )
            session.commit()
            result = marketing_metrics(session, date(2026, 9, 1), date(2026, 9, 8))
        vk = next(row for row in result["channels"] if row["source"] == "vk")
        self.assertEqual(vk["leads"], 1)
        self.assertEqual(vk["expenses"], "6000.00")
        self.assertEqual(vk["paid_revenue"], "9000.00")
        self.assertEqual(vk["cpl"], "6000.00")
        self.assertEqual(vk["roas"], "1.50")
        self.assertEqual(result["unassigned_ad_expenses"], "500.00")

    def test_marketing_metrics_ignores_forwarded_localhost_header(self):
        client = TestClient(main.app, client=("192.168.1.25", 50000))
        response = client.get(
            "/api/analytics/marketing?start_date=2026-09-01&end_date=2026-09-08",
            headers={"X-Forwarded-For": "127.0.0.1"},
        )
        self.assertEqual(response.status_code, 403)

    def test_editing_income_preserves_its_channel(self):
        with Session(self.engine) as session:
            row = Transaction(
                source="manual",
                operation_date=date(2026, 9, 8),
                amount=Decimal("3000.00"),
                category="Дезинсекция",
                channel="Яндекс",
                kind="income",
                review_required=False,
            )
            session.add(row)
            session.commit()
            row_id = row.id
        updated = main.update_transaction(
            row_id, main.TransactionPatchIn(description="Уточнено")
        )
        self.assertEqual(updated.channel, "Яндекс")
