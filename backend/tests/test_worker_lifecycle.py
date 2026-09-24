import io
import logging
import os
import threading
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from app import background_workers, main, tg_poller
from app.background_workers import ThreadWorker, WorkerRegistry
from app.models import Base
from app.reports import scheduler


def wait_for_stop(stop: threading.Event):
    def run() -> None:
        stop.wait()

    return run


class WorkerLifecycleTest(unittest.TestCase):
    def setUp(self) -> None:
        self.registry = WorkerRegistry()
        self._poller = tg_poller._poller_worker
        self._scheduler = scheduler._scheduler_worker
        self._summary = getattr(main.app.state, "worker_shutdown_summary", None)
        self._logger_disabled = background_workers.LOG.disabled
        self._logging_disable = logging.root.manager.disable
        self._threads_before = set(threading.enumerate())
        tg_poller._poller_worker = None
        scheduler._scheduler_worker = None
        main.app.state.worker_shutdown_summary = None
        background_workers.LOG.disabled = False
        logging.disable(logging.NOTSET)

    def tearDown(self) -> None:
        self.registry.shutdown(timeout=1)
        remaining = [
            thread.name
            for thread in threading.enumerate()
            if thread not in self._threads_before and thread.name.startswith("ekodez-")
        ]
        tg_poller._poller_worker = self._poller
        scheduler._scheduler_worker = self._scheduler
        main.app.state.worker_shutdown_summary = self._summary
        background_workers.LOG.disabled = self._logger_disabled
        logging.disable(self._logging_disable)
        self.assertEqual(remaining, [], "application workers survived test teardown")

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
                with (
                    self.assertNoLogs("app.background_workers", level="WARNING"),
                    TestClient(main.app),
                ):
                    extra_stop = threading.Event()
                    extra = ThreadWorker(
                        "ekodez-future-worker",
                        wait_for_stop(extra_stop),
                        stop_event=extra_stop,
                    )
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
        registry = self.registry
        second_stop = threading.Event()
        second = ThreadWorker(
            "second", wait_for_stop(second_stop), stop_event=second_stop
        )

        first_stop = threading.Event()

        def wait_for_both() -> None:
            first_stop.wait()
            second.stop_event.wait()

        first = ThreadWorker("first", wait_for_both, stop_event=first_stop)
        registry.start(first)
        registry.start(second)
        try:
            summary = registry.shutdown(timeout=1)
            self.assertEqual(summary, {"stopped": ["first", "second"], "timed_out": []})
            self.assertFalse(first.thread.is_alive())
            self.assertFalse(second.thread.is_alive())
        finally:
            first.stop_event.set()
            second.stop_event.set()
            first.thread.join(1)
            second.thread.join(1)

    def test_registry_reports_timeout_instead_of_claiming_clean_shutdown(self):
        release = threading.Event()
        registry = self.registry

        def blocked() -> None:
            release.wait()

        worker = ThreadWorker("blocked-worker", blocked)
        registry.start(worker)
        try:
            with self.assertLogs("app.background_workers", level="WARNING") as logs:
                summary = registry.shutdown(timeout=0.01)
            self.assertEqual(summary, {"stopped": [], "timed_out": ["blocked-worker"]})
            self.assertIn("blocked-worker", "\n".join(logs.output))
            self.assertTrue(worker.stop_event.is_set())
        finally:
            release.set()
            worker.thread.join(1)

    def test_lifespan_shutdown_marks_stuck_worker_degraded_without_raising(self):
        release = threading.Event()

        def wait_for_release() -> None:
            release.wait()

        worker = ThreadWorker("stuck-worker", wait_for_release)
        original_shutdown = WorkerRegistry.shutdown
        with (
            patch.object(main, "start_poller"),
            patch.object(main, "start_report_scheduler"),
            patch.object(main, "RetentionWorker", return_value=worker),
            patch.object(WorkerRegistry, "shutdown", autospec=True) as shutdown,
        ):
            shutdown.side_effect = lambda registry: original_shutdown(
                registry, timeout=0.01
            )
            try:
                with TestClient(main.app):
                    pass
                health = main.health()
                self.assertEqual(health["status"], "ok")
                self.assertEqual(health["reports_status"], "degraded")
                self.assertEqual(health["reports_reason"], "workers_stuck")
            finally:
                release.set()
                worker.thread.join(1)
