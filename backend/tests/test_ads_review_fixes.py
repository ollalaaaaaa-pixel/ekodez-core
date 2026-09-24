import unittest
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.ads.config import AdsConfig
from app.ads.metrics import ads_metrics
from app.ads.parsers import parse_ads_file
from app.models import Base, Lead, Notification, SchedulerJobRun, Transaction
from app.reports.scheduler import run_due_ads_jobs


class AdsReviewFixesTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.addCleanup(self.engine.dispose)

    def test_monday_slot_catches_up_on_tuesday_exactly_once(self):
        tz = ZoneInfo("Europe/Moscow")
        last = datetime(2026, 9, 14, 9, 9, tzinfo=tz)
        now = datetime(2026, 9, 15, 9, 16, tzinfo=tz)
        config = AdsConfig(root=Path("unused"), platforms={})
        with (
            patch("app.reports.scheduler.load_ads_config", return_value=config),
            patch(
                "app.reports.scheduler.run_ads_weekly", return_value={"delivered": True}
            ),
        ):
            self.assertEqual(
                run_due_ads_jobs(self.engine, now, last),
                ("import", "reminders", "weekly"),
            )
            self.assertEqual(run_due_ads_jobs(self.engine, now, last), ())
        with Session(self.engine) as session:
            runs = session.scalars(select(SchedulerJobRun)).all()
            self.assertEqual(len(runs), 3)
            self.assertTrue(
                all(row.scheduled_for.date() == last.date() for row in runs)
            )

    def test_payment_for_old_lead_without_spend_produces_no_spend_row(self):
        with Session(self.engine) as session:
            lead = Lead(
                source="2gis",
                status="new",
                amount=Decimal("0"),
                performed_by="Артём",
                created_at=datetime(2026, 8, 25),
                attributed_platform="2gis",
                utm_campaign="review",
            )
            session.add(lead)
            session.flush()
            session.add(
                Transaction(
                    source="manual",
                    operation_date=date(2026, 9, 10),
                    amount=Decimal("6000"),
                    currency="RUB",
                    kind="income",
                    review_required=False,
                    needs_review=False,
                    lead_id=lead.id,
                )
            )
            session.commit()
            rows = ads_metrics(session, date(2026, 9, 1), date(2026, 9, 30))
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0].revenue, Decimal("6000.00"))
            self.assertIsNone(rows[0].romi)
            self.assertEqual(rows[0].romi_reason, "no_spend")
            lead.utm_campaign = None
            session.commit()
            rows = ads_metrics(session, date(2026, 9, 1), date(2026, 9, 30))
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0].revenue, Decimal("6000.00"))
            self.assertEqual(rows[0].romi_reason, "no_spend")

    def test_weekly_two_false_results_persist_failure_and_do_not_resend(self):
        config = AdsConfig(root=Path("unused"), platforms={})
        now = datetime(2026, 9, 14, 9, 30, tzinfo=ZoneInfo("Europe/Moscow"))
        with (
            patch("app.reports.scheduler.load_ads_config", return_value=config),
            patch("app.ads.agent.load_ads_config", return_value=config),
            patch.dict(
                "os.environ", {"TELEGRAM_BOT_TOKEN": "synthetic", "OWNER_TG_ID": "1"}
            ),
            patch("app.reports.scheduler.send_message", return_value=False) as sender,
        ):
            run_due_ads_jobs(self.engine, now)
            run_due_ads_jobs(self.engine, now)
            self.assertEqual(sender.call_count, 2)
        with Session(self.engine) as s:
            self.assertEqual(s.scalar(select(SchedulerJobRun.status)), "failed")
            self.assertEqual(
                len(
                    s.scalars(
                        select(Notification).where(
                            Notification.kind == "ads_delivery_failed"
                        )
                    ).all()
                ),
                1,
            )

    def test_period_end_uses_max_of_explicit_row_date_and_granularity(self):
        for explicit, expected in (
            ("", date(2026, 10, 3)),
            ("05.10.2026", date(2026, 10, 5)),
        ):
            with self.subTest(explicit=explicit):
                rows = [
                    ["Отчет за месяц"],
                    ["Кампания", "Начало периода", "Дата", "Конец периода", "Расход"],
                    ["review", "01.09.2026", "10.09.2026", explicit, "1000"],
                    ["other", "01.09.2026", "03.10.2026", explicit, "2000"],
                ]
                with patch("app.ads.parsers._read_rows", return_value=rows):
                    parsed = parse_ads_file(Path("review.csv"), "2gis")
                self.assertTrue(
                    all(row.period_end == expected for row in parsed.spend_rows)
                )
