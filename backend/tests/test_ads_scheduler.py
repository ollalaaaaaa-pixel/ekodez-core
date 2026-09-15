import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

from sqlalchemy import create_engine

from app.ads.config import AdsConfig, PlatformConfig
from app.models import Base
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


if __name__ == "__main__":
    unittest.main()
