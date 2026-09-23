import io
import os
import threading
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from app import main, tg_poller
from app.background_workers import ThreadWorker, WorkerRegistry
from app.models import Base
from app.reports import scheduler


def wait_for_stop(stop: threading.Event) -> None:
    stop.wait()


class WorkerLifecycleTest(unittest.TestCase):
    def test_shutdown_joins_all_workers_and_has_no_network_after_teardown(self):
        engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(engine)
        before = set(threading.enumerate())
        polled = threading.Event()
        scheduled = threading.Event()
        exited = threading.Event()
        late_network = threading.Event()
        crashes: list[object] = []

        def network(*args, **kwargs):
            if exited.is_set():
                late_network.set()
            polled.set()
            return io.BytesIO(b'{"ok": true, "result": []}')

        with (
            patch.object(main, "engine", engine),
            patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "synthetic-lifecycle"}),
            patch("urllib.request.urlopen", side_effect=network),
            patch.object(tg_poller, "_load_offset", return_value=0),
            patch.object(tg_poller, "_save_offset"),
            patch.object(tg_poller, "purge_expired_client_drafts"),
            patch("app.security.pii_retention.purge_expired_lead_pii", return_value=0),
            patch.object(
                scheduler,
                "run_scheduler_iteration",
                side_effect=lambda *args: scheduled.set(),
            ),
            patch.object(threading, "excepthook", side_effect=crashes.append),
        ):
            try:
                with TestClient(main.app):
                    extra = ThreadWorker("ekodez-future-worker", wait_for_stop)
                    main.app.state.worker_registry.start(extra)
                    self.assertTrue(polled.wait(2), "poller did not start")
                    self.assertTrue(scheduled.wait(2), "scheduler did not start")
                exited.set()
                remaining = [t.name for t in threading.enumerate() if t not in before]
                self.assertEqual(remaining, [], "application workers survived shutdown")
                self.assertFalse(late_network.wait(2.2))
                self.assertEqual(crashes, [])
            finally:
                engine.dispose()

    def test_registry_signals_all_workers_before_joining(self):
        registry = WorkerRegistry()
        second = ThreadWorker("second", wait_for_stop)

        def wait_for_both(stop):
            stop.wait()
            second.stop_event.wait()

        first = ThreadWorker("first", wait_for_both)
        registry.start(first)
        registry.start(second)
        try:
            registry.shutdown(timeout=1)
            self.assertFalse(first.thread.is_alive())
            self.assertFalse(second.thread.is_alive())
        finally:
            first.stop_event.set()
            second.stop_event.set()
            first.thread.join(1)
            second.thread.join(1)

    def test_registry_reports_timeout_instead_of_claiming_clean_shutdown(self):
        release = threading.Event()
        registry = WorkerRegistry()

        def blocked(stop: threading.Event) -> None:
            release.wait()

        worker = ThreadWorker("blocked-worker", blocked)
        registry.start(worker)
        try:
            with self.assertRaisesRegex(RuntimeError, "shutdown timed out"):
                registry.shutdown(timeout=0.01)
            self.assertTrue(worker.stop_event.is_set())
        finally:
            release.set()
            registry.shutdown(timeout=1)
