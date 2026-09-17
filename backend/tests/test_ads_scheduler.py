import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.ads.config import AdsConfig, PlatformConfig
from app.models import Base, Notification, SchedulerJobRun
from app.reports import scheduler


class AdsSchedulerTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)

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
        with Session(self.engine) as session:
            run = session.scalar(select(SchedulerJobRun))
            self.assertEqual(run.status, "ok")

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

    def test_failure_in_one_due_job_does_not_block_neighboring_minutes(self):
        config = AdsConfig(root=Path("C:/synthetic-ads"), platforms={})
        monday = datetime(2026, 9, 14, 9, 15, tzinfo=ZoneInfo("Europe/Moscow"))
        with (
            patch(
                "app.reports.scheduler.load_ads_config",
                side_effect=[RuntimeError("boom"), config],
            ),
            patch("app.reports.scheduler.create_upload_reminders", return_value=[]),
        ):
            self.assertEqual(scheduler.run_due_ads_jobs(self.engine, monday), ())
            self.assertEqual(
                scheduler.run_due_ads_jobs(self.engine, monday.replace(minute=20)),
                ("reminders",),
            )
        with Session(self.engine) as session:
            statuses = {
                row.job_name: row.status
                for row in session.scalars(select(SchedulerJobRun)).all()
            }
            self.assertEqual(statuses, {"ads_import": "failed", "ads_reminders": "ok"})

    def test_scheduler_poll_delay_never_exceeds_one_minute(self):
        now = datetime(2026, 9, 14, 8, 1, tzinfo=ZoneInfo("Europe/Moscow"))
        self.assertLessEqual(scheduler.poll_delay_seconds(now), 60.0)

    def test_long_job_catches_up_missed_0915_import_at_0916(self):
        config = AdsConfig(root=Path("C:/synthetic-ads"), platforms={})
        monday = datetime(2026, 9, 14, 9, 10, tzinfo=ZoneInfo("Europe/Moscow"))
        with (
            patch("app.reports.scheduler.run_due_auto", return_value=False),
            patch("app.reports.scheduler.load_ads_config", return_value=config),
        ):
            scheduler.run_scheduler_iteration(self.engine, monday)
            scheduler.run_scheduler_iteration(self.engine, monday.replace(minute=16))
        with Session(self.engine) as session:
            runs = session.scalars(select(SchedulerJobRun)).all()
            self.assertEqual(
                [(row.job_name, row.status) for row in runs], [("ads_import", "ok")]
            )
            self.assertEqual(
                session.get(
                    scheduler.SchedulerState, "core"
                ).last_iteration_time.minute,
                16,
            )

    def test_stale_running_attempt_is_recorded_and_retried(self):
        config = AdsConfig(root=Path("C:/synthetic-ads"), platforms={})
        monday = datetime(2026, 9, 14, 9, 16, tzinfo=ZoneInfo("Europe/Moscow"))
        with Session(self.engine) as session:
            session.add(
                SchedulerJobRun(
                    run_key="2026-09-14:ads_import",
                    job_name="ads_import",
                    scheduled_for=monday.replace(minute=15),
                    status="running",
                    started_at=monday.replace(hour=7, minute=15),
                )
            )
            session.commit()
        with patch("app.reports.scheduler.load_ads_config", return_value=config):
            self.assertEqual(
                scheduler.run_due_ads_jobs(
                    self.engine, monday, monday.replace(minute=10)
                ),
                ("import",),
            )
        with Session(self.engine) as session:
            attempts = session.scalars(
                select(SchedulerJobRun).order_by(SchedulerJobRun.id)
            ).all()
            self.assertEqual([row.status for row in attempts], ["stale_failed", "ok"])
            self.assertEqual(attempts[0].error_type, "LeaseExpired")

    def test_stale_ads_attempt_recovers_after_iteration_cursor_passed_schedule(self):
        config = AdsConfig(root=Path("C:/synthetic-ads"), platforms={})
        now = datetime(2026, 9, 14, 10, 0, tzinfo=ZoneInfo("Europe/Moscow"))
        with Session(self.engine) as session:
            session.add(
                SchedulerJobRun(
                    run_key="2026-09-14:ads_import",
                    job_name="ads_import",
                    scheduled_for=now.replace(hour=9, minute=15),
                    status="running",
                    started_at=now.replace(hour=9, minute=15),
                )
            )
            session.commit()
        with patch("app.reports.scheduler.load_ads_config", return_value=config):
            self.assertEqual(
                scheduler.run_due_ads_jobs(
                    self.engine, now, now.replace(hour=9, minute=59)
                ),
                ("import",),
            )
        with Session(self.engine) as session:
            rows = session.scalars(
                select(SchedulerJobRun).order_by(SchedulerJobRun.id)
            ).all()
            self.assertEqual([row.status for row in rows], ["stale_failed", "ok"])

    def test_daily_failure_does_not_block_ads_job_in_same_iteration(self):
        now = datetime(2026, 9, 14, 9, 15, tzinfo=ZoneInfo("Europe/Moscow"))
        with (
            patch(
                "app.reports.scheduler.run_due_auto", side_effect=RuntimeError("boom")
            ),
            patch(
                "app.reports.scheduler.run_due_ads_jobs", return_value=("import",)
            ) as ads,
        ):
            scheduler.run_scheduler_iteration(self.engine, now)
        ads.assert_called_once_with(
            self.engine,
            now,
            now.replace(hour=0, minute=0, second=0, microsecond=0)
            - scheduler.timedelta(microseconds=1),
        )


if __name__ == "__main__":
    unittest.main()
