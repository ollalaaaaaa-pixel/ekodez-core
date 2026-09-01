import unittest
from datetime import date
from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.business_calendar import CalendarRangeError, add_business_days, is_business_day
from app.contracts import get_or_create_period, is_paid_month, next_invoice_number
from app.models import Base, Contract, ContractPeriod


class RussianBusinessCalendarTest(unittest.TestCase):
    def test_2026_official_holidays_and_five_business_days(self):
        self.assertFalse(is_business_day(date(2026, 1, 9)))
        self.assertFalse(is_business_day(date(2026, 2, 23)))
        self.assertTrue(is_business_day(date(2026, 2, 24)))
        self.assertEqual(add_business_days(date(2026, 2, 20), 5), date(2026, 3, 2))
        self.assertEqual(add_business_days(date(2026, 12, 24), 5), date(2027, 1, 11))

    def test_calendar_rejects_dates_outside_2025_2027(self):
        with self.assertRaises(CalendarRangeError):
            is_business_day(date(2028, 1, 10))


class ContractRulesTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)

    def tearDown(self):
        self.engine.dispose()

    @staticmethod
    def _contract(periodicity: str, service_months: list[int] | None = None):
        return Contract(
            number=f"test-{periodicity}",
            price=Decimal("5000.00"),
            periodicity=periodicity,
            service_months=service_months,
        )

    def test_paid_months_follow_owner_selected_schedule(self):
        self.assertTrue(is_paid_month(self._contract("monthly"), date(2026, 9, 1)))
        semiannual = self._contract("semiannual", [3, 9])
        self.assertTrue(is_paid_month(semiannual, date(2026, 9, 1)))
        self.assertFalse(is_paid_month(semiannual, date(2026, 8, 1)))
        custom = self._contract("custom", [1, 5, 10])
        self.assertTrue(is_paid_month(custom, date(2026, 10, 1)))

    def test_period_inherits_preparations_and_uses_editable_defaults(self):
        with Session(self.engine) as session:
            contract = self._contract("semiannual", [3, 9])
            session.add(contract)
            session.flush()
            previous = ContractPeriod(
                contract=contract,
                period_month=date(2026, 8, 1),
                paid_service_due=False,
                preparations="Клеевая ловушка; приманка",
                infestation_degree="средняя",
                extra_services=["Осмотр подвала"],
            )
            session.add(previous)
            session.commit()

            period = get_or_create_period(session, contract, date(2026, 9, 18))
            self.assertEqual(period.period_month, date(2026, 9, 1))
            self.assertTrue(period.paid_service_due)
            self.assertEqual(period.price_snapshot, Decimal("5000.00"))
            self.assertEqual(period.preparations, "Клеевая ловушка; приманка")
            self.assertEqual(period.infestation_degree, "начальная")
            self.assertEqual(period.extra_services, [])

    def test_invoice_number_is_next_numeric_value_and_remains_editable(self):
        with Session(self.engine) as session:
            contract = self._contract("monthly")
            session.add(contract)
            session.flush()
            session.add_all(
                [
                    ContractPeriod(
                        contract=contract,
                        period_month=date(2026, 7, 1),
                        paid_service_due=True,
                        price_snapshot=contract.price,
                        invoice_number="41",
                    ),
                    ContractPeriod(
                        contract=contract,
                        period_month=date(2026, 8, 1),
                        paid_service_due=True,
                        price_snapshot=contract.price,
                        invoice_number="СФ-август",
                    ),
                ]
            )
            session.commit()

            self.assertEqual(next_invoice_number(session), "42")


if __name__ == "__main__":
    unittest.main()
