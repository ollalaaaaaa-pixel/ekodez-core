import io
import tempfile
import unittest
from datetime import datetime, timedelta
from html import escape
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

from cryptography.fernet import Fernet
from openpyxl import Workbook
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session

from app.ads.config import AdsConfig
from app.models import Base, GnomSettings, GnomWeeklyRun, SchedulerJobRun
from app.reports.scheduler import run_due_gnom_job


class GnomLeaseTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.addCleanup(self.engine.dispose)
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        for target, value in (
            ("app.gnom_scheduler.IMPORT_ROOT", Path(folder.name)),
            (
                "app.reports.scheduler.load_ads_config",
                AdsConfig(root=Path(folder.name), platforms={}),
            ),
        ):
            mock = (
                patch(target, return_value=value)
                if target.endswith("load_ads_config")
                else patch(target, value)
            )
            mock.start()
            self.addCleanup(mock.stop)
        env = patch.dict(
            "os.environ", {"TELEGRAM_BOT_TOKEN": "synthetic", "OWNER_TG_ID": "1"}
        )
        env.start()
        self.addCleanup(env.stop)
        send = patch("app.tg_poller.send_message", return_value=True)
        self.sender = send.start()
        self.addCleanup(send.stop)
        self.slot = datetime(2026, 9, 14, 9, 10, tzinfo=ZoneInfo("Europe/Moscow"))
        with Session(self.engine) as s:
            s.add(GnomSettings(id=1, weekly_enabled=True))
            s.commit()

    def seed_running(self):
        with Session(self.engine) as s:
            s.add(
                GnomWeeklyRun(
                    week=self.slot.date(),
                    status="running",
                    started_at=self.slot.replace(tzinfo=None),
                )
            )
            s.add(
                SchedulerJobRun(
                    run_key="2026-09-14:gnom_weekly",
                    job_name="gnom_weekly",
                    scheduled_for=self.slot,
                    started_at=self.slot,
                    status="running",
                )
            )
            s.commit()

    def statuses(self):
        with Session(self.engine) as s:
            return (
                list(
                    s.scalars(
                        select(SchedulerJobRun.status).order_by(SchedulerJobRun.id)
                    )
                ),
                s.get(GnomWeeklyRun, self.slot.date()).status,
            )

    def test_35_minutes_blocks_new_attempt_and_never_marks_ok(self):
        self.seed_running()
        now = self.slot + timedelta(minutes=35)
        self.assertFalse(run_due_gnom_job(self.engine, now, now - timedelta(minutes=1)))
        self.assertEqual(self.statuses(), (["stale_failed"], "running"))
        self.sender.assert_not_called()

    def test_120_minutes_recovers_real_inner_state_once_with_stale_history(self):
        from app.models import GnomWeeklyAttempt

        self.seed_running()
        first = self.slot + timedelta(minutes=35)
        self.assertFalse(
            run_due_gnom_job(self.engine, first, first - timedelta(minutes=1))
        )
        now = self.slot + timedelta(minutes=120)
        self.assertTrue(run_due_gnom_job(self.engine, now, now - timedelta(minutes=1)))
        self.assertFalse(
            run_due_gnom_job(self.engine, now, self.slot - timedelta(minutes=1))
        )
        self.assertEqual(self.statuses(), (["stale_failed", "ok"], "sent"))
        self.assertEqual(self.sender.call_count, 1)
        with Session(self.engine) as s:
            attempts = s.scalars(
                select(GnomWeeklyAttempt).order_by(GnomWeeklyAttempt.id)
            ).all()
            self.assertEqual([a.status for a in attempts], ["stale_failed", "sent"])
            self.assertEqual(attempts[0].error_type, "LeaseExpired")

    def test_monday_gnom_slot_runs_on_tuesday_and_is_not_duplicated(self):
        now = self.slot + timedelta(days=1, minutes=6)
        last = self.slot - timedelta(minutes=1)
        self.assertTrue(run_due_gnom_job(self.engine, now, last))
        self.assertFalse(run_due_gnom_job(self.engine, now, last))
        self.assertEqual(self.sender.call_count, 1)
        self.assertEqual(self.statuses(), (["ok"], "sent"))

    def test_fresh_outer_run_blocks_even_when_inner_is_stale(self):
        self.seed_running()
        now = self.slot + timedelta(hours=2)
        with Session(self.engine) as s:
            outer = s.scalar(select(SchedulerJobRun))
            outer.started_at = (now - timedelta(minutes=10)).replace(tzinfo=None)
            s.commit()
        self.assertFalse(run_due_gnom_job(self.engine, now, now - timedelta(minutes=1)))
        self.assertEqual(self.statuses(), (["running"], "running"))
        self.sender.assert_not_called()


class GnomStoredPiiRegressionTest(unittest.TestCase):
    def test_sql_scan_all_formats_and_error_has_no_plain_pii(self):
        from app.gnom_parser import HEADERS, GnomError
        from app.gnom_service import import_file
        from tests.test_gnom import TEST_NAME, TEST_PHONE, csv_bytes, fixture

        row = fixture()
        book = Workbook()
        book.active.append(list(HEADERS))
        book.active.append([row[key] for key in HEADERS])
        output = io.BytesIO()
        book.save(output)
        book.close()
        html = (
            "<table>"
            + "".join(
                "<tr>"
                + "".join(
                    "<td>" + escape(value).replace("\n", "<br>") + "</td>"
                    for value in cells
                )
                + "</tr>"
                for cells in (list(HEADERS), [row[key] for key in HEADERS])
            )
            + "</table>"
        )
        cases = (
            ("csv", csv_bytes([row])),
            ("xlsx", output.getvalue()),
            ("xls", html.encode()),
            ("error.csv", b"bad;header\n1;2"),
        )
        with patch.dict(
            "os.environ", {"PII_FERNET_KEY": Fernet.generate_key().decode()}
        ):
            for suffix, content in cases:
                with self.subTest(suffix=suffix):
                    engine = create_engine("sqlite:///:memory:")
                    try:
                        Base.metadata.create_all(engine)
                        filename = f"{TEST_NAME}-{TEST_PHONE}.{suffix}"
                        if suffix == "error.csv":
                            with self.assertRaises(GnomError):
                                import_file(engine, content, filename, authorized=True)
                        else:
                            import_file(engine, content, filename, authorized=True)
                        with Session(engine) as s:
                            for table in Base.metadata.sorted_tables:
                                saved = str(
                                    s.execute(
                                        text(f'SELECT * FROM "{table.name}"')
                                    ).all()
                                )
                                for secret in (
                                    TEST_PHONE,
                                    TEST_PHONE[1:],
                                    TEST_NAME,
                                    "Тестнапарник",
                                    "Тестовая",
                                ):
                                    self.assertNotIn(secret, saved, table.name)
                    finally:
                        engine.dispose()
