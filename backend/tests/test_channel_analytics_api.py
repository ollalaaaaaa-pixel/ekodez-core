import unittest
from datetime import date
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app import main
from app.channels import CHANNELS
from app.models import Base, ExpenseCategory, Transaction


class ChannelAnalyticsApiTest(unittest.TestCase):
    def setUp(self):
        self.original_engine = main.engine
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        main.engine = self.engine
        with Session(self.engine) as session:
            session.add(ExpenseCategory(name="Еда"))
            session.commit()

    def tearDown(self):
        main.engine = self.original_engine
        self.engine.dispose()

    def add_transaction(
        self,
        *,
        operation_date: date,
        amount: str,
        kind: str = "income",
        channel: str | None = None,
    ) -> None:
        with Session(self.engine) as session:
            session.add(
                Transaction(
                    source="manual",
                    operation_date=operation_date,
                    amount=Decimal(amount),
                    category="Другие работы" if kind == "income" else "Еда",
                    kind=kind,
                    channel=channel,
                    review_required=False,
                )
            )
            session.commit()

    def test_owner_approved_channels_are_accepted_for_income(self):
        self.assertEqual(
            CHANNELS,
            ("Яндекс", "2ГИС", "Авито", "ВК", "Сарафан", "Прочее"),
        )
        for channel in CHANNELS:
            with self.subTest(channel=channel):
                row = main.create_day_entry(
                    main.DayEntryIn(
                        kind="income",
                        category="Другие работы",
                        amount=Decimal("100.00"),
                        channel=channel,
                        date=date(2026, 8, 16),
                    )
                )
                self.assertEqual(row.channel, channel)

    def test_unknown_income_channel_is_rejected_for_both_create_routes(self):
        with self.assertRaises(HTTPException) as day_error:
            main.create_day_entry(
                main.DayEntryIn(
                    kind="income",
                    category="Другие работы",
                    amount=Decimal("100.00"),
                    channel="Телеграм",
                    date=date(2026, 8, 16),
                )
            )
        self.assertEqual(day_error.exception.status_code, 422)

        with self.assertRaises(HTTPException) as transaction_error:
            main.create_transaction(
                main.TransactionIn(
                    operation_date=date(2026, 8, 16),
                    amount=Decimal("100.00"),
                    kind="income",
                    channel="Телеграм",
                )
            )
        self.assertEqual(transaction_error.exception.status_code, 422)

    def test_expense_channel_is_always_cleared(self):
        row = main.create_day_entry(
            main.DayEntryIn(
                kind="expense",
                category="Еда",
                amount=Decimal("500.00"),
                channel="Авито",
                date=date(2026, 8, 16),
            )
        )
        self.assertIsNone(row.channel)

    def test_analytics_aggregates_channels_and_filters_kind_and_dates(self):
        self.add_transaction(
            operation_date=date(2026, 8, 1), amount="5000.00", channel="Авито"
        )
        self.add_transaction(
            operation_date=date(2026, 8, 31), amount="7000.00", channel="Авито"
        )
        self.add_transaction(
            operation_date=date(2026, 8, 15), amount="10000.00", channel="Сарафан"
        )
        self.add_transaction(
            operation_date=date(2026, 8, 15), amount="3000.00", channel=None
        )
        self.add_transaction(
            operation_date=date(2026, 8, 15),
            amount="99000.00",
            kind="expense",
            channel="Авито",
        )
        self.add_transaction(
            operation_date=date(2026, 7, 31), amount="8000.00", channel="Яндекс"
        )

        result = main.channel_analytics(date(2026, 8, 1), date(2026, 8, 31))

        self.assertEqual(result["period_total"], Decimal("25000.00"))
        self.assertEqual(
            result["channels"],
            [
                {
                    "channel": "Авито",
                    "total_amount": Decimal("12000.00"),
                    "count": 2,
                    "avg_check": Decimal("6000.00"),
                    "share_percent": Decimal("48.00"),
                },
                {
                    "channel": "Сарафан",
                    "total_amount": Decimal("10000.00"),
                    "count": 1,
                    "avg_check": Decimal("10000.00"),
                    "share_percent": Decimal("40.00"),
                },
                {
                    "channel": "Не указан",
                    "total_amount": Decimal("3000.00"),
                    "count": 1,
                    "avg_check": Decimal("3000.00"),
                    "share_percent": Decimal("12.00"),
                },
            ],
        )

    def test_blank_channels_join_the_not_specified_group(self):
        self.add_transaction(
            operation_date=date(2026, 8, 16), amount="100.00", channel=None
        )
        self.add_transaction(
            operation_date=date(2026, 8, 16), amount="200.00", channel=""
        )
        self.add_transaction(
            operation_date=date(2026, 8, 16), amount="300.00", channel="   "
        )

        result = main.channel_analytics(date(2026, 8, 16), date(2026, 8, 16))

        self.assertEqual(
            result["channels"],
            [
                {
                    "channel": "Не указан",
                    "total_amount": Decimal("600.00"),
                    "count": 3,
                    "avg_check": Decimal("200.00"),
                    "share_percent": Decimal("100.00"),
                }
            ],
        )

    def test_invalid_or_empty_period_has_a_deterministic_result(self):
        with self.assertRaises(HTTPException) as error:
            main.channel_analytics(date(2026, 8, 2), date(2026, 8, 1))
        self.assertEqual(error.exception.status_code, 422)

        self.assertEqual(
            main.channel_analytics(date(2026, 7, 1), date(2026, 7, 31)),
            {"period_total": Decimal("0.00"), "channels": []},
        )


if __name__ == "__main__":
    unittest.main()
