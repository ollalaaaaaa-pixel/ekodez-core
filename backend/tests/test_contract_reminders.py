import unittest
from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models import Base, Contract, ContractPeriod, Object, Transaction
from app.reports.daily import build_contract_reminders, format_contract_reminders


class ContractReminderTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)

    def tearDown(self):
        self.engine.dispose()

    def _object(self) -> Object:
        return Object(
            name="ТЕСТ Хостел",
            address="г. Архангельск, секретный адрес",
            type="other",
            area_sqm=Decimal("90.00"),
            risk_points=[],
            status="active",
            contract=Contract(
                number="ТЕСТ-01",
                price=Decimal("5000.00"),
                periodicity="monthly",
                service_months=[],
            ),
        )

    def test_acts_are_reminded_only_on_25th_until_package_generated(self):
        with Session(self.engine) as session:
            service_object = self._object()
            session.add(service_object)
            session.commit()

            before = build_contract_reminders(session, date(2026, 9, 24))
            on_date = build_contract_reminders(session, date(2026, 9, 25))
            self.assertEqual(before.acts_to_issue, ())
            self.assertEqual(on_date.acts_to_issue[0].object_name, "ТЕСТ Хостел")

            session.add(
                ContractPeriod(
                    contract=service_object.contract,
                    period_month=date(2026, 9, 1),
                    paid_service_due=True,
                    price_snapshot=Decimal("5000.00"),
                    generated_at=datetime(2026, 9, 25, 8, 0, tzinfo=UTC),
                )
            )
            session.commit()
            after = build_contract_reminders(session, date(2026, 9, 25))
            self.assertEqual(after.acts_to_issue, ())

    def test_overdue_payment_disappears_after_explicit_income_link(self):
        with Session(self.engine) as session:
            service_object = self._object()
            session.add(service_object)
            session.flush()
            period = ContractPeriod(
                contract=service_object.contract,
                period_month=date(2026, 9, 1),
                paid_service_due=True,
                price_snapshot=Decimal("5000.00"),
                invoice_number="1",
                work_act_status="signed",
                work_act_signed_at=datetime(2026, 9, 1, 12, 0, tzinfo=UTC),
            )
            session.add(period)
            session.commit()

            reminders = build_contract_reminders(session, date(2026, 9, 10))
            self.assertEqual(len(reminders.overdue_payments), 1)
            text = format_contract_reminders(reminders)
            self.assertIn("Просрочена оплата", text)
            self.assertNotIn("секретный адрес", text)

            transaction = Transaction(
                source="manual",
                operation_date=date(2026, 9, 10),
                amount=Decimal("5000.00"),
                kind="income",
                review_required=False,
                needs_review=False,
                object_id=service_object.id,
            )
            session.add(transaction)
            session.flush()
            period.transaction_id = transaction.id
            session.commit()
            paid = build_contract_reminders(session, date(2026, 9, 10))
            self.assertEqual(paid.overdue_payments, ())


if __name__ == "__main__":
    unittest.main()
