import io
import json
import tempfile
import threading
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app import main, tg_poller
from app.models import Base, GnomSettings, SchedulerJobRun, SchedulerState
from app.reports import scheduler
from app.security.pii_retention import RetentionWorker
from scripts import backend_watchdog, maintenance


class MaintenanceModeTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite:///:memory:", connect_args={"check_same_thread": False}
        )
        self.addCleanup(self.engine.dispose)

    def test_http_health_and_watchdog_stay_healthy_in_maintenance(self):
        with (
            patch.object(Path, "read_text", return_value='{"maintenance_mode":true}'),
            patch.object(main, "engine", self.engine),
        ):
            client = TestClient(main.app)
            self.addCleanup(client.close)
            for path in ("/health", "/health/db"):
                response = client.get(path)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()["status"], "ok")
                if path == "/health":
                    self.assertEqual(response.json()["reports_status"], "degraded")
                    self.assertEqual(
                        response.json()["reports_reason"], "maintenance_mode"
                    )
            with (
                patch.object(
                    backend_watchdog, "probe_health", return_value=True
                ) as probe,
                patch.object(backend_watchdog, "notify_owner") as notify,
            ):
                event = backend_watchdog.cycle(
                    backend_watchdog.State(),
                    1000,
                    lambda: False,
                    probe,
                    lambda: self.fail("healthy backend must not restart"),
                    notify,
                    lambda state: None,
                )
            self.assertEqual(event, "healthy")
            probe.assert_called_once()
            notify.assert_not_called()

    def test_manual_today_and_whoami_remain_available_in_dry_mode(self):
        Base.metadata.create_all(self.engine)
        with (
            patch.object(Path, "read_text", return_value='{"maintenance_mode":true}'),
            patch.object(tg_poller, "_send_message") as send,
        ):
            for command in ("/whoami", "/today"):
                tg_poller._process_update(
                    "synthetic",
                    self.engine,
                    {
                        "message": {
                            "text": command,
                            "from": {"id": 1},
                            "chat": {"id": 1, "type": "private"},
                        },
                    },
                    {1: "owner"},
                )
        self.assertEqual(send.call_count, 2)
        self.assertEqual(send.call_args_list[0].args, ("synthetic", 1, "1"))
        self.assertEqual(send.call_args_list[1].args[1], 1)

    def test_switch_enabled_between_jobs_prevents_remaining_jobs(self):
        with (
            patch.object(
                Path,
                "read_text",
                side_effect=[
                    '{"maintenance_mode":false}',
                    '{"maintenance_mode":false}',
                    '{"maintenance_mode":true}',
                ],
            ),
            patch.object(scheduler, "_last_iteration"),
            patch.object(scheduler, "_record_iteration"),
            patch.object(scheduler, "run_due_gnom_job") as gnom,
            patch.object(scheduler, "run_due_auto") as daily,
            patch.object(scheduler, "run_due_ads_jobs") as ads,
        ):
            scheduler.run_scheduler_iteration(
                self.engine, datetime.now(ZoneInfo("Europe/Moscow"))
            )
        gnom.assert_called_once()
        daily.assert_not_called()
        ads.assert_not_called()

    def test_explicit_false_restores_weekly_summary_delivery(self):
        Base.metadata.create_all(self.engine)
        now = datetime(2026, 9, 28, 14, 31, tzinfo=ZoneInfo("Europe/Moscow"))
        with Session(self.engine) as session:
            session.add(
                SchedulerState(
                    name="core",
                    last_iteration_time=now.replace(hour=9, minute=29, tzinfo=None),
                )
            )
            session.commit()
        with (
            patch.object(
                Path,
                "read_text",
                return_value='{"maintenance_mode":false,"platforms":{}}',
            ),
            patch.dict(
                "os.environ", {"TELEGRAM_BOT_TOKEN": "synthetic", "OWNER_TG_ID": "1"}
            ),
            patch.object(scheduler, "send_message", return_value=True) as send,
        ):
            scheduler.run_scheduler_iteration(self.engine, now)
        send.assert_called_once()
        with Session(self.engine) as session:
            rows = session.scalars(select(SchedulerJobRun)).all()
            self.assertEqual(
                [(row.job_name, row.status) for row in rows], [("ads_weekly", "ok")]
            )

    def test_only_explicit_false_allows_automation_and_config_is_hot_read(self):
        with tempfile.TemporaryDirectory() as folder:
            config = Path(folder) / "config.json"
            with patch.object(maintenance, "CONFIG_PATH", config):
                self.assertTrue(maintenance.maintenance_enabled())
                for value in (True, "false", 0, None):
                    config.write_text(json.dumps({"maintenance_mode": value}))
                    self.assertTrue(maintenance.maintenance_enabled())
                for raw in ("{", "{}", "[]"):
                    config.write_text(raw)
                    self.assertTrue(maintenance.maintenance_enabled())
                config.write_text('{"maintenance_mode":false}')
                self.assertFalse(maintenance.maintenance_enabled())
                config.write_text('{"maintenance_mode":true}')
                self.assertTrue(maintenance.maintenance_enabled())
                with patch.object(Path, "read_text", side_effect=PermissionError):
                    self.assertTrue(maintenance.maintenance_enabled())

    def test_dry_scheduler_creates_no_job_runs_and_advances_cursor(self):
        engine = create_engine("sqlite:///:memory:")
        self.addCleanup(engine.dispose)
        Base.metadata.create_all(engine)
        now = datetime(2026, 9, 28, 9, 31, tzinfo=ZoneInfo("Europe/Moscow"))
        with Session(engine) as session:
            session.add(GnomSettings(id=1, weekly_enabled=True))
            session.add(
                SchedulerState(
                    name="core", last_iteration_time=now.replace(minute=9, tzinfo=None)
                )
            )
            session.commit()
        with (
            patch.object(Path, "read_text", return_value='{"maintenance_mode":true}'),
            patch(
                "urllib.request.urlopen",
                side_effect=AssertionError("unexpected network"),
            ) as network,
            patch.object(scheduler, "import_ads_file") as importer,
        ):
            scheduler.run_scheduler_iteration(engine, now)
        network.assert_not_called()
        importer.assert_not_called()
        with Session(engine) as session:
            self.assertEqual(
                session.scalar(select(func.count()).select_from(SchedulerJobRun)), 0
            )
            row = session.get(SchedulerState, "core")
            assert row is not None
            self.assertEqual(row.last_iteration_time, now.replace(tzinfo=None))

    def test_manual_health_and_status_reply_only_to_configured_staff(self):
        engine = create_engine("sqlite:///:memory:")
        self.addCleanup(engine.dispose)
        Base.metadata.create_all(engine)
        with (
            patch.object(Path, "read_text", return_value='{"maintenance_mode":true}'),
            patch.object(tg_poller, "_send_message") as send,
            patch.object(tg_poller, "receive_client_message") as intake,
            patch.object(tg_poller, "_handle_agent_message") as agent,
        ):
            for actor in (1, 2, 3):
                for command in ("/health", "/status"):
                    tg_poller._process_update(
                        "synthetic",
                        engine,
                        {
                            "update_id": actor,
                            "message": {
                                "from": {"id": actor},
                                "chat": {"id": actor, "type": "private"},
                                "text": command,
                            },
                        },
                        {1: "owner", 2: "master"},
                    )
        self.assertEqual(send.call_count, 4)
        self.assertEqual({call.args[1] for call in send.call_args_list}, {1, 2})
        self.assertTrue(
            all("maintenance" in call.args[2] for call in send.call_args_list)
        )
        intake.assert_not_called()
        agent.assert_not_called()

    def test_maintenance_blocks_channel_import_quiz_alert_and_callbacks(self):
        with (
            patch.object(Path, "read_text", return_value='{"maintenance_mode":true}'),
            patch.object(tg_poller, "_ingest") as ingest,
            patch.object(tg_poller, "receive_client_message") as intake,
            patch.object(tg_poller, "_handle_callback") as callback,
            patch.object(tg_poller, "_send_message") as send,
        ):
            updates: list[dict] = [
                {"channel_post": {"text": "id сделки: 123"}},
                {
                    "update_id": 1,
                    "message": {
                        "from": {"id": 3},
                        "chat": {"id": 3, "type": "private"},
                        "text": "/start quiz_test",
                    },
                },
                {"callback_query": {"id": "test", "data": "confirm"}},
            ]
            for update in updates:
                tg_poller._process_update("synthetic", object(), update, {1: "owner"})
        ingest.assert_not_called()
        intake.assert_not_called()
        callback.assert_not_called()
        send.assert_not_called()

    def test_poller_keeps_reading_updates_but_skips_background_draft_purge(self):
        engine = create_engine("sqlite:///:memory:")
        self.addCleanup(engine.dispose)
        stop = threading.Event()

        def get_updates(*args, **kwargs):
            stop.set()
            return io.BytesIO(b'{"ok":true,"result":[]}')

        with (
            patch.object(Path, "read_text", return_value='{"maintenance_mode":true}'),
            patch.object(tg_poller, "_load_offset", return_value=0),
            patch.object(tg_poller, "purge_expired_client_drafts") as purge,
            patch("urllib.request.urlopen", side_effect=get_updates) as network,
        ):
            tg_poller._loop("synthetic", engine, stop)
        self.assertEqual(network.call_count, 1)
        purge.assert_not_called()

    def test_scheduler_skips_every_business_job_and_weekly_sender(self):
        with (
            patch.object(Path, "read_text", return_value='{"maintenance_mode":true}'),
            patch.object(scheduler, "_last_iteration"),
            patch.object(scheduler, "_record_iteration"),
            patch.object(scheduler, "run_due_gnom_job") as gnom,
            patch.object(scheduler, "run_due_auto") as daily,
            patch.object(scheduler, "run_due_ads_jobs") as ads,
            patch.object(scheduler, "send_message") as send,
            # Alembic's fileConfig in prior migration tests disables old loggers.
            patch.object(maintenance.LOG, "disabled", False),
            self.assertLogs(maintenance.LOG, level="WARNING") as logs,
        ):
            scheduler.run_scheduler_iteration(
                self.engine,
                datetime(2026, 9, 28, 9, 31, tzinfo=ZoneInfo("Europe/Moscow")),
            )
        gnom.assert_not_called()
        daily.assert_not_called()
        ads.assert_not_called()
        send.assert_not_called()
        self.assertIn("skipped due to maintenance mode", "\n".join(logs.output))

    def test_retention_worker_skips_automatic_purge(self):
        worker = RetentionWorker(self.engine)
        with (
            patch.object(Path, "read_text", return_value='{"maintenance_mode":true}'),
            patch.object(worker.stop_event, "wait", return_value=True),
            patch("app.security.pii_retention.purge_expired_lead_pii") as purge,
        ):
            worker.run()
        purge.assert_not_called()

    def test_watchdog_suppresses_automatic_telegram_notification(self):
        with (
            patch.object(Path, "read_text", return_value='{"maintenance_mode":true}'),
            patch.dict(
                "os.environ", {"TELEGRAM_BOT_TOKEN": "synthetic", "OWNER_TG_ID": "1"}
            ),
            patch("urllib.request.urlopen") as network,
        ):
            backend_watchdog.notify_owner(backend_watchdog.ALERT)
        network.assert_not_called()
