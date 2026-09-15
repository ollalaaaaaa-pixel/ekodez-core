import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.ads.config import AdsConfig, PlatformConfig
from app.models import Base, Notification
from app.reports import scheduler


class AdsSchedulerTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        scheduler._ads_job_runs.clear()

    def tearDown(self):
        self.engine.dispose()

    def test_import_runs_only_monday_0915_and_once(self):
        config = AdsConfig(
            root=Path("C:/synthetic-ads"),
            platforms={"2gis": PlatformConfig(mode="disabled")},
        )
        monday = datetime(2026, 9, 14, 9, 15, tzinfo=ZoneInfo("Europe/Moscow"))
        with patch("app.reports.scheduler.load_ads_config", return_value=config):
            self.assertEqual(
                scheduler.run_due_ads_jobs(self.engine, monday), ("import",)
            )
            self.assertEqual(scheduler.run_due_ads_jobs(self.engine, monday), ())
            self.assertEqual(
                scheduler.run_due_ads_jobs(self.engine, monday.replace(minute=14)), ()
            )

    def test_reminder_payload_is_copied_before_session_closes(self):
        config = AdsConfig(
            root=Path("C:/synthetic-ads"),
            platforms={"2gis": PlatformConfig(reminder_period_days=7)},
        )
        monday = datetime(2026, 9, 14, 9, 20, tzinfo=ZoneInfo("Europe/Moscow"))
        messages: list[str] = []

        def record_message(*_: object) -> bool:
            messages.append("sent")
            return True

        with (
            patch("app.reports.scheduler.load_ads_config", return_value=config),
            patch(
                "app.reports.scheduler.send_message",
                side_effect=record_message,
            ),
            patch.dict(
                "os.environ", {"TELEGRAM_BOT_TOKEN": "token", "OWNER_TG_ID": "1"}
            ),
        ):
            self.assertEqual(
                scheduler.run_due_ads_jobs(self.engine, monday), ("reminders",)
            )
        self.assertEqual(messages, ["sent"])
        with Session(self.engine) as session:
            self.assertEqual(len(session.scalars(select(Notification)).all()), 1)


if __name__ == "__main__":
    unittest.main()
