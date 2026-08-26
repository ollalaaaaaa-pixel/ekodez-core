import io
import os
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stderr
from datetime import date, datetime
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch
from zoneinfo import ZoneInfo

from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from alembic import command
from app import main
from app.models import Base, Inventory, Lead, Object, SentReport, Transaction

MOSCOW_TZ = ZoneInfo("Europe/Moscow")


class DailyReportPersistenceTest(unittest.TestCase):
    def setUp(self):
        self.original_engine = main.engine
        self.engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        main.engine = self.engine
        with Session(self.engine) as session:
            session.add(Lead(source="telegram", status="new"))
            session.commit()

    def tearDown(self):
        main.engine = self.original_engine
        self.engine.dispose()

    def test_status_transition_records_closure_and_reopen_clears_it(self):
        client = TestClient(main.app, client=("127.0.0.1", 50000))

        closed = client.post("/api/leads/1/status", json={"status": "done"})
        self.assertEqual(closed.status_code, 200)
        with Session(self.engine) as session:
            row = session.get(Lead, 1)
            assert row is not None
            first_closed_at = row.closed_at
        self.assertIsNotNone(first_closed_at)

        repeated = client.post("/api/leads/1/status", json={"status": "done"})
        self.assertEqual(repeated.status_code, 200)
        with Session(self.engine) as session:
            row = session.get(Lead, 1)
            assert row is not None
            self.assertEqual(row.closed_at, first_closed_at)

        reopened = client.post("/api/leads/1/status", json={"status": "in_work"})
        self.assertEqual(reopened.status_code, 200)
        with Session(self.engine) as session:
            row = session.get(Lead, 1)
            assert row is not None
            self.assertIsNone(row.closed_at)
        client.close()

    def test_sent_report_supports_recipient_status_per_attempt(self):
        sent_at = datetime(2026, 8, 26, 9, 0, tzinfo=MOSCOW_TZ)
        with Session(self.engine) as session:
            session.add_all(
                [
                    SentReport(
                        report_date=sent_at.date(),
                        report_type="manual",
                        recipient_key="owner",
                        status="sent",
                        sent_at=sent_at,
                    ),
                    SentReport(
                        report_date=sent_at.date(),
                        report_type="manual",
                        recipient_key="owner",
                        status="failed",
                        sent_at=sent_at,
                    ),
                ]
            )
            session.commit()
            rows = session.scalars(select(SentReport).order_by(SentReport.id)).all()

        self.assertEqual([row.status for row in rows], ["sent", "failed"])
        self.assertEqual({row.recipient_key for row in rows}, {"owner"})


class DailyReportMigrationTest(unittest.TestCase):
    def test_sqlite_upgrade_preserves_leads_and_adds_daily_report_schema(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = os.path.join(temp_dir, "daily-reports.db")
            database_url = f"sqlite:///{database_path}"
            config = Config(
                os.path.join(os.path.dirname(__file__), "..", "alembic.ini")
            )
            with patch.dict(os.environ, {"DATABASE_URL": database_url}, clear=False):
                command.upgrade(config, "a4d9c2e7f613")
                engine = main.create_app_engine(database_url)
                with engine.begin() as connection:
                    connection.execute(
                        text(
                            "INSERT INTO leads (source, status, created_at) "
                            "VALUES ('telegram', 'done', '2026-08-20 10:00:00')"
                        )
                    )
                    connection.execute(
                        text(
                            "INSERT INTO objects "
                            "(name, address, type, area_sqm, risk_points, status) "
                            "VALUES ('Объект', 'Бизнес-адрес', 'office', "
                            "10, '[]', 'active')"
                        )
                    )
                    connection.execute(
                        text(
                            "INSERT INTO treatments "
                            "(lead_id, object_id, chemicals_used, performed_at, "
                            "performed_by) VALUES "
                            "(1, 1, '[]', '2026-08-20 10:00:00', 'Артём')"
                        )
                    )
                engine.dispose()

                command.upgrade(config, "head")
                verified = main.create_app_engine(database_url)
                schema = inspect(verified)
                self.assertIn(
                    "closed_at", {c["name"] for c in schema.get_columns("leads")}
                )
                self.assertIn("sent_reports", schema.get_table_names())
                self.assertIn(
                    "uq_sent_reports_successful_auto_recipient_date",
                    {row["name"] for row in schema.get_indexes("sent_reports")},
                )
                self.assertEqual(
                    {"report_date", "report_type", "recipient_key", "status", "sent_at"}
                    - {c["name"] for c in schema.get_columns("sent_reports")},
                    set(),
                )
                with verified.connect() as connection:
                    self.assertEqual(
                        connection.execute(text("SELECT COUNT(*) FROM leads")).scalar(),
                        1,
                    )
                    self.assertIsNone(
                        connection.execute(text("SELECT closed_at FROM leads")).scalar()
                    )
                    self.assertEqual(
                        connection.execute(
                            text("SELECT lead_id FROM treatments")
                        ).scalar(),
                        1,
                    )
                verified.dispose()


class DailySnapshotTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.report_date = date(2026, 8, 25)
        with Session(self.engine) as session:
            session.add_all(
                [
                    Transaction(
                        source="manual",
                        operation_date=self.report_date,
                        amount=Decimal("1000.10"),
                        kind="income",
                        review_required=False,
                        needs_review=True,
                    ),
                    Transaction(
                        source="manual",
                        operation_date=self.report_date,
                        amount=Decimal("250.05"),
                        kind="expense",
                        review_required=False,
                    ),
                    Transaction(
                        source="manual",
                        operation_date=self.report_date,
                        amount=Decimal("5000.00"),
                        kind="income",
                        review_required=True,
                    ),
                    Lead(
                        source="telegram",
                        status="new",
                        phone="8921***5000",
                        created_at=datetime(2026, 8, 25, 8, 0),
                    ),
                    Lead(
                        source="telegram",
                        status="done",
                        created_at=datetime(2026, 8, 20, 8, 0),
                        closed_at=datetime(2026, 8, 25, 18, 0),
                    ),
                    Lead(
                        source="telegram",
                        status="done",
                        created_at=datetime(2026, 8, 20, 8, 0),
                        closed_at=None,
                    ),
                ]
            )
            for index in range(11):
                session.add(
                    Object(
                        name=f"Объект-{index:02d}",
                        address=f"СЕКРЕТНЫЙ-АДРЕС-{index}",
                        type="office",
                        area_sqm=Decimal("100.00"),
                        risk_points=[],
                        next_treatment_date=date(2026, 8, 24),
                        status="active",
                    )
                )
                session.add(
                    Inventory(
                        chemical_name=f"Препарат-{index:02d}",
                        quantity=Decimal("0.050"),
                        initial_quantity=Decimal("1.000"),
                        unit="л",
                        batch_number=f"batch-{index}",
                        expiry_date=date(2027, 1, 1),
                        supplier="Поставщик",
                    )
                )
            session.commit()

    def tearDown(self):
        self.engine.dispose()

    def test_snapshot_uses_decimal_business_rules_and_safe_text(self):
        from app.reports.daily import build_daily_snapshot, format_daily_report

        with Session(self.engine) as session:
            snapshot = build_daily_snapshot(session, self.report_date)

        self.assertEqual(snapshot.revenue, Decimal("1000.10"))
        self.assertEqual(snapshot.expenses, Decimal("250.05"))
        self.assertEqual(snapshot.profit, Decimal("750.05"))
        self.assertEqual(snapshot.margin_pct, Decimal("75.00"))
        self.assertEqual(snapshot.new_leads, 1)
        self.assertEqual(snapshot.closed_leads, 1)
        self.assertEqual(snapshot.disputed_operations, 1)
        self.assertEqual(len(snapshot.overdue_objects), 11)
        self.assertEqual(len(snapshot.low_stock_items), 11)

        message = format_daily_report(snapshot)
        self.assertIn("Сводка ЭКОДЕЗ за 25.08.2026", message)
        self.assertIn("1 000.10 ₽", message)
        self.assertIn("250.05 ₽", message)
        self.assertIn("Новые: 1", message)
        self.assertIn("Закрытые: 1", message)
        self.assertLessEqual(message.count("Объект-"), 10)
        self.assertLessEqual(message.count("Препарат-"), 10)
        self.assertIn("… и ещё 1", message)
        self.assertNotIn("8921", message)
        self.assertNotIn("СЕКРЕТНЫЙ-АДРЕС", message)

    def test_message_stays_within_telegram_limit_for_maximum_names(self):
        from app.reports.daily import build_daily_snapshot, format_daily_report

        with Session(self.engine) as session:
            for service_object in session.scalars(select(Object)):
                service_object.name = "Я" * 300
            for inventory_item in session.scalars(select(Inventory)):
                inventory_item.chemical_name = "Х" * 200
            session.commit()
            message = format_daily_report(
                build_daily_snapshot(session, self.report_date)
            )

        self.assertLessEqual(len(message), 4096)
        self.assertNotIn("1E+", message)


class DailyDeliveryTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.now = datetime(2026, 8, 26, 9, 0, tzinfo=MOSCOW_TZ)

    def tearDown(self):
        self.engine.dispose()

    def test_successful_manual_delivery_records_owner_status(self):
        from app.reports.daily import send_daily_report

        calls = []

        def sender(token, chat_id, message):
            calls.append((token, chat_id, message))
            return True

        with patch.dict(
            os.environ,
            {
                "TELEGRAM_BOT_TOKEN": "token-marker",
                "OWNER_TG_ID": "12345",
                "ALEXEY_TG_ID": "67890",
            },
            clear=True,
        ):
            result = send_daily_report(self.engine, "manual", self.now, sender=sender)

        self.assertEqual(result.status, "sent")
        self.assertEqual(result.recipient_key, "owner")
        self.assertEqual(result.report_date, self.now.date())
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][1], 12345)
        self.assertNotIn("token-marker", calls[0][2])
        with Session(self.engine) as session:
            row = session.scalar(select(SentReport))
            assert row is not None
            self.assertEqual(row.id, result.id)

    def test_missing_or_invalid_owner_configuration_is_rejected(self):
        from app.reports.daily import ReportsConfigurationError, send_daily_report

        for environment in (
            {},
            {"TELEGRAM_BOT_TOKEN": "token-marker"},
            {"TELEGRAM_BOT_TOKEN": "token-marker", "OWNER_TG_ID": "invalid"},
        ):
            with (
                self.subTest(environment=sorted(environment)),
                patch.dict(os.environ, environment, clear=True),
                self.assertRaises(ReportsConfigurationError),
            ):
                send_daily_report(
                    self.engine, "manual", self.now, sender=lambda *_: True
                )

    def test_failed_sender_records_failed_attempt(self):
        from app.reports.daily import TelegramDeliveryError, send_daily_report

        with (
            patch.dict(
                os.environ,
                {"TELEGRAM_BOT_TOKEN": "token-marker", "OWNER_TG_ID": "12345"},
                clear=True,
            ),
            self.assertRaises(TelegramDeliveryError),
        ):
            send_daily_report(self.engine, "manual", self.now, sender=lambda *_: False)

        with Session(self.engine) as session:
            row = session.scalar(select(SentReport))
            assert row is not None
            self.assertEqual(row.status, "failed")
            self.assertEqual(row.recipient_key, "owner")

    def test_second_auto_returns_existing_success_without_sending_again(self):
        from app.reports.daily import send_daily_report

        calls = []

        def sender(*args):
            calls.append(args)
            return True

        environment = {
            "TELEGRAM_BOT_TOKEN": "token-marker",
            "OWNER_TG_ID": "12345",
        }
        with patch.dict(os.environ, environment, clear=True):
            first = send_daily_report(self.engine, "auto", self.now, sender=sender)
            second = send_daily_report(self.engine, "auto", self.now, sender=sender)

        self.assertEqual(second.id, first.id)
        self.assertEqual(len(calls), 1)

    def test_manual_cooldown_rejects_59_seconds_and_allows_exactly_60(self):
        from app.reports.daily import ManualReportCooldown, send_daily_report

        calls = []

        def sender(*args):
            calls.append(args)
            return True

        environment = {
            "TELEGRAM_BOT_TOKEN": "token-marker",
            "OWNER_TG_ID": "12345",
        }
        with patch.dict(os.environ, environment, clear=True):
            send_daily_report(self.engine, "manual", self.now, sender=sender)
            with self.assertRaises(ManualReportCooldown) as caught:
                send_daily_report(
                    self.engine,
                    "manual",
                    self.now.replace(second=59),
                    sender=sender,
                )
            self.assertEqual(caught.exception.retry_after_seconds, 1)
            send_daily_report(
                self.engine,
                "manual",
                self.now.replace(minute=1),
                sender=sender,
            )

        self.assertEqual(len(calls), 2)

    def test_concurrent_auto_sends_only_once(self):
        from app.reports.daily import send_daily_report

        with tempfile.TemporaryDirectory() as temp_dir:
            engine = create_engine(
                f"sqlite:///{os.path.join(temp_dir, 'auto.db')}",
                connect_args={"check_same_thread": False},
            )
            Base.metadata.create_all(engine)
            call_count = 0
            call_guard = threading.Lock()

            def sender(*_):
                nonlocal call_count
                with call_guard:
                    call_count += 1
                time.sleep(0.1)
                return True

            environment = {
                "TELEGRAM_BOT_TOKEN": "token-marker",
                "OWNER_TG_ID": "12345",
            }
            with (
                patch.dict(os.environ, environment, clear=True),
                ThreadPoolExecutor(max_workers=2) as pool,
            ):
                futures = [
                    pool.submit(
                        send_daily_report,
                        engine,
                        "auto",
                        self.now,
                        sender,
                    )
                    for _ in range(2)
                ]
                results = [future.result() for future in futures]

            self.assertEqual(call_count, 1)
            self.assertEqual(results[0].id, results[1].id)
            engine.dispose()

    def test_concurrent_manual_requests_enforce_cooldown(self):
        from app.reports.daily import ManualReportCooldown, send_daily_report

        with tempfile.TemporaryDirectory() as temp_dir:
            engine = create_engine(
                f"sqlite:///{os.path.join(temp_dir, 'manual.db')}",
                connect_args={"check_same_thread": False},
            )
            Base.metadata.create_all(engine)
            call_count = 0
            call_guard = threading.Lock()

            def sender(*_):
                nonlocal call_count
                with call_guard:
                    call_count += 1
                time.sleep(0.1)
                return True

            def attempt():
                try:
                    return send_daily_report(
                        engine, "manual", self.now, sender=sender
                    ).status
                except ManualReportCooldown:
                    return "cooldown"

            environment = {
                "TELEGRAM_BOT_TOKEN": "token-marker",
                "OWNER_TG_ID": "12345",
            }
            with (
                patch.dict(os.environ, environment, clear=True),
                ThreadPoolExecutor(max_workers=2) as pool,
            ):
                results = list(pool.map(lambda _: attempt(), range(2)))

            self.assertEqual(call_count, 1)
            self.assertEqual(sorted(results), ["cooldown", "sent"])
            engine.dispose()


class DailySchedulerTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)

    def tearDown(self):
        self.engine.dispose()

    def test_catchup_window_and_next_check_points(self):
        from app.reports.scheduler import next_check_at, within_catchup_window

        day = date(2026, 8, 26)
        before = datetime(2026, 8, 26, 8, 59, tzinfo=MOSCOW_TZ)
        self.assertFalse(within_catchup_window(before))
        self.assertEqual(
            next_check_at(before),
            datetime.combine(day, datetime.min.time()).replace(
                hour=9, tzinfo=MOSCOW_TZ
            ),
        )
        self.assertTrue(
            within_catchup_window(datetime(2026, 8, 26, 9, 0, tzinfo=MOSCOW_TZ))
        )
        middle = datetime(2026, 8, 26, 10, 37, tzinfo=MOSCOW_TZ)
        self.assertTrue(within_catchup_window(middle))
        self.assertEqual(
            next_check_at(middle),
            datetime(2026, 8, 26, 11, 0, tzinfo=MOSCOW_TZ),
        )
        end = datetime(2026, 8, 26, 12, 0, tzinfo=MOSCOW_TZ)
        self.assertTrue(within_catchup_window(end))
        delayed_final_check = datetime(2026, 8, 26, 12, 0, 1, tzinfo=MOSCOW_TZ)
        self.assertTrue(within_catchup_window(delayed_final_check))
        after = datetime(2026, 8, 26, 13, 0, tzinfo=MOSCOW_TZ)
        self.assertFalse(within_catchup_window(after))
        self.assertEqual(
            next_check_at(after),
            datetime(2026, 8, 27, 9, 0, tzinfo=MOSCOW_TZ),
        )

    def test_due_auto_calls_service_directly_and_skips_success(self):
        from app.reports import scheduler

        now = datetime(2026, 8, 26, 10, 37, tzinfo=MOSCOW_TZ)
        with patch.object(scheduler, "send_daily_report") as send:
            self.assertTrue(scheduler.run_due_auto(self.engine, now))
            send.assert_called_once_with(self.engine, "auto", now)

        with Session(self.engine) as session:
            session.add(
                SentReport(
                    report_date=now.date(),
                    report_type="auto",
                    recipient_key="owner",
                    status="sent",
                    sent_at=now,
                )
            )
            session.commit()
        with patch.object(scheduler, "send_daily_report") as send:
            self.assertFalse(scheduler.run_due_auto(self.engine, now))
            send.assert_not_called()

    def test_missing_configuration_is_degraded_and_starts_no_thread(self):
        from app.reports import scheduler

        scheduler._scheduler_started = False
        warning = io.StringIO()
        with (
            patch.dict(os.environ, {}, clear=True),
            patch.object(scheduler.threading, "Thread") as thread,
            redirect_stderr(warning),
        ):
            scheduler.start_report_scheduler(self.engine)

        thread.assert_not_called()
        self.assertEqual(scheduler.reports_status(), "degraded")
        self.assertIn('"event": "reports_scheduler_degraded"', warning.getvalue())

    def test_configured_scheduler_starts_once_and_health_is_ok(self):
        from app.reports import scheduler

        scheduler._scheduler_started = False
        environment = {
            "TELEGRAM_BOT_TOKEN": "token-marker",
            "OWNER_TG_ID": "12345",
        }
        with (
            patch.dict(os.environ, environment, clear=True),
            patch.object(scheduler.threading, "Thread") as thread,
        ):
            scheduler.start_report_scheduler(self.engine)
            scheduler.start_report_scheduler(self.engine)
            self.assertEqual(scheduler.reports_status(), "ok")
            self.assertEqual(main.health()["reports"], "ok")

        thread.assert_called_once()
        thread.return_value.start.assert_called_once()
        scheduler._scheduler_started = False


class DailyReportApiTest(unittest.TestCase):
    def setUp(self):
        self.original_engine = main.engine
        self.engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        main.engine = self.engine
        self.sent_at = datetime(2026, 8, 26, 13, 0, tzinfo=MOSCOW_TZ)
        self.result = SimpleNamespace(
            status="sent",
            report_date=self.sent_at.date(),
            sent_at=self.sent_at,
            recipient_key="owner",
        )

    def tearDown(self):
        main.engine = self.original_engine
        self.engine.dispose()

    def test_non_local_client_is_forbidden_and_proxy_header_is_ignored(self):
        client = TestClient(main.app, client=("198.51.100.10", 51000))
        with patch.object(main, "send_daily_report") as send:
            response = client.post(
                "/api/reports/daily/send",
                headers={"X-Forwarded-For": "127.0.0.1"},
            )
        client.close()

        self.assertEqual(response.status_code, 403)
        send.assert_not_called()

    def test_localhost_manual_send_returns_only_delivery_metadata(self):
        client = TestClient(main.app, client=("127.0.0.1", 51000))
        with patch.object(main, "send_daily_report", return_value=self.result) as send:
            response = client.post("/api/reports/daily/send")
        client.close()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            set(response.json()),
            {"status", "report_date", "sent_at", "recipient_key"},
        )
        self.assertEqual(response.json()["recipient_key"], "owner")
        self.assertEqual(send.call_args.args[:2], (self.engine, "manual"))

    def test_manual_cooldown_returns_429_and_retry_after(self):
        from app.reports.daily import ManualReportCooldown

        client = TestClient(main.app, client=("::1", 51000))
        with patch.object(
            main, "send_daily_report", side_effect=ManualReportCooldown(17)
        ):
            response = client.post("/api/reports/daily/send")
        client.close()

        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.headers["retry-after"], "17")

    def test_configuration_and_delivery_failures_have_safe_statuses(self):
        from app.reports.daily import (
            ReportsConfigurationError,
            TelegramDeliveryError,
        )

        client = TestClient(main.app, client=("127.0.0.1", 51000))
        cases = (
            (ReportsConfigurationError("secret detail"), 503),
            (TelegramDeliveryError("secret detail"), 502),
        )
        for error, expected_status in cases:
            with (
                self.subTest(expected_status=expected_status),
                patch.object(main, "send_daily_report", side_effect=error),
            ):
                response = client.post("/api/reports/daily/send")
            self.assertEqual(response.status_code, expected_status)
            self.assertNotIn("secret detail", response.text)
        client.close()


if __name__ == "__main__":
    unittest.main()
