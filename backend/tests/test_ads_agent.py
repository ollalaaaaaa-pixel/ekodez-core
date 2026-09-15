import smtplib
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.ads.agent import create_upload_reminders, run_ads_weekly
from app.ads.config import AdsConfig, PlatformConfig
from app.models import AdImportRun, AdSpend, Base, Lead, Notification


class AdsReminderAgentTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.config = AdsConfig(
            root=Path("C:/synthetic-ads"),
            platforms={"2gis": PlatformConfig(reminder_period_days=7)},
        )
        self.now = datetime(2026, 9, 14, 9, 20, tzinfo=UTC)

    def tearDown(self):
        self.engine.dispose()

    def test_upload_reminder_is_created_once_per_period(self):
        with Session(self.engine) as session:
            self.assertEqual(
                len(create_upload_reminders(session, self.config, self.now)), 1
            )
            session.commit()
            self.assertEqual(
                len(create_upload_reminders(session, self.config, self.now)), 0
            )
            self.assertEqual(len(session.scalars(select(Notification)).all()), 1)

    def test_fresh_successful_import_suppresses_upload_reminder(self):
        with Session(self.engine) as session:
            session.add(
                AdImportRun(
                    platform="2gis",
                    source_file="report.xlsx",
                    status="ok",
                    rows_imported=3,
                    period_start=self.now.date() - timedelta(days=7),
                    period_end=self.now.date() - timedelta(days=1),
                    created_at=self.now - timedelta(days=1),
                )
            )
            session.commit()
            self.assertEqual(
                create_upload_reminders(session, self.config, self.now), []
            )

    def test_recent_upload_of_stale_period_does_not_suppress_reminder(self):
        with Session(self.engine) as session:
            session.add(
                AdImportRun(
                    platform="2gis",
                    source_file="file-0123456789ab.xlsx",
                    status="ok",
                    rows_imported=3,
                    period_start=self.now.date() - timedelta(days=40),
                    period_end=self.now.date() - timedelta(days=30),
                    created_at=self.now - timedelta(hours=1),
                )
            )
            session.commit()
            self.assertEqual(
                len(create_upload_reminders(session, self.config, self.now)), 1
            )

    def test_weekly_agent_alerts_only_after_two_high_cpl_weeks_and_never_emails(self):
        config = AdsConfig(
            root=Path("C:/synthetic-ads"),
            platforms={
                "2gis": PlatformConfig(
                    target_cpl=Decimal("500"),
                    zero_lead_spend_threshold=Decimal("5000"),
                )
            },
        )
        with Session(self.engine) as session:
            session.add_all(
                [
                    AdSpend(
                        platform="2gis",
                        campaign="card",
                        period_start=self.now.date() - timedelta(days=14),
                        period_end=self.now.date() - timedelta(days=8),
                        spend=Decimal("1000"),
                        impressions=100,
                        clicks=10,
                        conversions=1,
                    ),
                    AdSpend(
                        platform="2gis",
                        campaign="card",
                        period_start=self.now.date() - timedelta(days=7),
                        period_end=self.now.date() - timedelta(days=1),
                        spend=Decimal("1200"),
                        impressions=100,
                        clicks=10,
                        conversions=1,
                    ),
                    Lead(
                        source="2gis",
                        status="new",
                        amount=Decimal("0"),
                        performed_by="Артём",
                        created_at=self.now - timedelta(days=10),
                        attributed_platform="2gis",
                        attribution_method="manual",
                    ),
                    Lead(
                        source="2gis",
                        status="new",
                        amount=Decimal("0"),
                        performed_by="Артём",
                        created_at=self.now - timedelta(days=3),
                        attributed_platform="2gis",
                        attribution_method="manual",
                    ),
                ]
            )
            session.commit()
        messages: list[str] = []
        with (
            tempfile.TemporaryDirectory() as temp_dir,
            patch("app.ads.agent.load_ads_config", return_value=config),
            patch("app.ads.agent.ANALYSIS_ROOT", Path(temp_dir)),
            patch.object(smtplib, "SMTP") as smtp,
            patch.object(smtplib, "SMTP_SSL") as smtp_ssl,
        ):
            result = run_ads_weekly(
                self.engine, self.now, lambda value: not messages.append(value)
            )
            self.assertEqual(len(result["drafts"]), 1)
            self.assertEqual(len(messages), 1)
            self.assertNotIn("телефон", messages[0].lower())
            self.assertNotIn("+7", messages[0])
            self.assertIn(
                "не отправлено", Path(result["drafts"][0]).read_text(encoding="utf-8")
            )
            smtp.assert_not_called()
            smtp_ssl.assert_not_called()


if __name__ == "__main__":
    unittest.main()
