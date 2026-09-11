import io
import unittest
from contextlib import redirect_stderr
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app import main
from app.models import Base, Lead
from app.security import pii_retention


class PiiRetentionTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.addCleanup(self.engine.dispose)

    def test_only_expired_closed_ciphertext_is_erased_and_repeat_is_noop(self):
        now = datetime(2026, 9, 11, 12, tzinfo=UTC)
        cutoff = datetime(2025, 9, 11, 12, tzinfo=UTC)
        cases = [
            ("done", cutoff - timedelta(microseconds=1), "old", None),
            ("cancelled", cutoff - timedelta(days=1), "cancelled", None),
            ("done", cutoff, "boundary", "boundary"),
            ("done", cutoff + timedelta(seconds=1), "recent", "recent"),
            ("new", cutoff - timedelta(days=5), "open", "open"),
            ("in_work", cutoff - timedelta(days=5), "working", "working"),
            ("done", None, "undated", "undated"),
            ("done", cutoff - timedelta(days=5), None, None),
        ]
        with Session(self.engine) as session:
            for status, closed_at, ciphertext, _ in cases:
                session.add(
                    Lead(
                        status=status,
                        closed_at=closed_at,
                        encrypted_pii=ciphertext,
                        client_name="Т***",
                        amount=Decimal("100.00"),
                    )
                )
            session.commit()
        self.assertEqual(pii_retention.purge_expired_lead_pii(self.engine, now), 2)
        self.assertEqual(pii_retention.purge_expired_lead_pii(self.engine, now), 0)
        with Session(self.engine) as session:
            rows = session.scalars(select(Lead).order_by(Lead.id)).all()
            self.assertEqual(len(rows), len(cases))
            for row, case in zip(rows, cases, strict=True):
                self.assertEqual(row.encrypted_pii, case[3])
                self.assertEqual(row.status, case[0])
                self.assertEqual(row.client_name, "Т***")
                self.assertEqual(row.amount, Decimal("100.00"))
                expected_date = case[1]
                self.assertEqual(
                    row.closed_at,
                    expected_date.replace(tzinfo=None) if expected_date else None,
                )

    def test_twelve_calendar_months_handle_leap_day(self):
        self.assertEqual(
            pii_retention.retention_cutoff(datetime(2024, 2, 29, 10, tzinfo=UTC)),
            datetime(2023, 2, 28, 10, tzinfo=UTC),
        )

    def test_cancellation_records_date_and_reopening_clears_it(self):
        with Session(self.engine) as session:
            session.add(Lead(status="new"))
            session.commit()
        with patch.object(main, "engine", self.engine):
            client = TestClient(main.app)
            closed: datetime | None = None
            for status in ("cancelled", "cancelled"):
                self.assertEqual(
                    client.post(
                        "/api/leads/1/status", json={"status": status}
                    ).status_code,
                    200,
                )
                with Session(self.engine) as session:
                    row = session.get(Lead, 1)
                    assert row is not None
                    self.assertIsNotNone(row.closed_at)
                    if closed is not None:
                        self.assertEqual(row.closed_at, closed)
                    closed = row.closed_at
            client.post("/api/leads/1/status", json={"status": "in_work"})
            with Session(self.engine) as session:
                row = session.get(Lead, 1)
                assert row is not None
                self.assertIsNone(row.closed_at)

    def test_worker_retries_without_logging_exception_details(self):
        worker = pii_retention.RetentionWorker(self.engine)
        captured = io.StringIO()
        with (
            patch.object(worker.stop_event, "wait", side_effect=[False, True]),
            patch.object(
                pii_retention,
                "purge_expired_lead_pii",
                side_effect=[RuntimeError("SENSITIVE_TEST_VALUE"), 2],
            ),
            redirect_stderr(captured),
        ):
            worker.run()
        output = captured.getvalue()
        self.assertIn("pii_retention_failed", output)
        self.assertIn('"erased": 2', output)
        self.assertNotIn("SENSITIVE_TEST_VALUE", output)

    def test_application_lifecycle_starts_and_stops_worker_without_telegram(self):
        with (
            patch.object(main, "engine", self.engine),
            patch.object(main, "start_poller"),
            patch.object(main, "start_report_scheduler"),
            TestClient(main.app) as client,
        ):
            worker = main.app.state.pii_retention_worker
            self.assertTrue(worker.thread.is_alive())
            self.assertEqual(client.get("/health/db").status_code, 200)
        self.assertFalse(worker.thread.is_alive())
