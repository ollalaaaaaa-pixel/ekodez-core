import asyncio
import json
import logging
import os
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

from scripts.backend_watchdog import (
    ALERT,
    State,
    clear_stale_restart_lock,
    cycle,
    probe_health,
    restart_lock_status,
    save_state,
)
from scripts.run_backend import IsoAccessFormatter, create_config


class WatchdogTest(unittest.TestCase):
    def setUp(self):
        self.state = State()
        self.restart = Mock(return_value=True)
        self.notify = Mock(return_value=True)
        self.saved = []

    def tick(self, now, healthy=False, deploying=False):
        with patch("scripts.backend_watchdog.time.time", return_value=now):
            return cycle(
                self.state,
                now,
                lambda: deploying,
                lambda: healthy,
                self.restart,
                self.notify,
                lambda state: self.saved.append((state.failures, state.cooldown_until)),
            )

    def test_two_failures_restart_once_and_send_only_safe_payload(self):
        self.assertEqual(self.tick(1000), "health_warning")
        self.restart.assert_not_called()
        self.assertEqual(self.tick(1300), "restarted")
        self.restart.assert_called_once()
        self.notify.assert_called_once_with(ALERT)
        self.assertEqual(ALERT, "backend перезапущен watchdog: health fail x2")
        self.assertNotIn("C:", ALERT)
        self.assertNotRegex(ALERT, r"\d{10,}")
        self.assertIn((0, 1900), self.saved)
        self.assertEqual(self.tick(1600), "cooldown")
        self.assertEqual(self.tick(1899), "cooldown")
        self.restart.assert_called_once()

    def test_deployment_flag_resets_sequence_and_disables_actions(self):
        self.tick(1000)
        self.assertEqual(self.tick(1300, deploying=True), "deploy_skip")
        self.assertEqual(self.tick(1600), "health_warning")
        self.restart.assert_not_called()
        self.notify.assert_not_called()

    def test_stale_lock_after_two_health_failures_restarts_once(self):
        with tempfile.TemporaryDirectory() as folder:
            lock = Path(folder) / "backend-restart.lock"
            lock.touch()
            os.utime(lock, (100, 100))

            def restart():
                self.assertFalse(lock.exists())
                return self.restart()

            for now, expected in ((1000, "health_warning"), (1300, "restarted")):

                def status(at_time: float = now) -> str:
                    return restart_lock_status(lock, at_time)

                def clear(at_time: float = now) -> bool:
                    return clear_stale_restart_lock(lock, at_time)

                self.assertEqual(
                    cycle(
                        self.state,
                        now,
                        lambda: False,
                        lambda: False,
                        restart,
                        self.notify,
                        lambda _: None,
                        lock_status=status,
                        clear_stale=clear,
                    ),
                    expected,
                )
            self.restart.assert_called_once()
            self.notify.assert_called_once_with(ALERT)

    def test_fresh_restart_lock_skips_health_and_restart(self):
        with tempfile.TemporaryDirectory() as folder:
            lock = Path(folder) / "backend-restart.lock"
            lock.touch()
            self.assertEqual(
                cycle(
                    self.state,
                    1000,
                    lambda: False,
                    Mock(),
                    self.restart,
                    self.notify,
                    lambda _: None,
                    lock_status=lambda: restart_lock_status(lock, 1000),
                    clear_stale=lambda: clear_stale_restart_lock(lock, 1000),
                ),
                "lock_busy",
            )
            self.restart.assert_not_called()

    def test_flag_appearing_during_probe_blocks_restart(self):
        self.state.failures = 1
        flag = Mock(side_effect=[False, True])
        self.assertEqual(
            cycle(
                self.state,
                1000,
                flag,
                lambda: False,
                self.restart,
                self.notify,
                lambda s: None,
            ),
            "deploy_skip",
        )
        self.restart.assert_not_called()

    def test_success_breaks_consecutive_failure_sequence(self):
        self.tick(1000)
        self.assertEqual(self.tick(1300, healthy=True), "healthy")
        self.assertEqual(self.tick(1600), "health_warning")
        self.restart.assert_not_called()

    def test_failed_restart_no_success_alert_and_cooldown_persisted(self):
        self.restart.side_effect = RuntimeError("private detail")
        self.tick(1000)
        self.assertEqual(self.tick(1300), "restart_failed")
        self.assertEqual(self.tick(1600), "cooldown")
        self.notify.assert_not_called()

    def test_state_survives_process_boundaries(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "state.json"
            save_state(path, State(1, 1900))
            state = State(**json.loads(path.read_text()))
            self.assertEqual(
                cycle(
                    state,
                    1600,
                    lambda: False,
                    Mock(),
                    self.restart,
                    self.notify,
                    Mock(),
                ),
                "cooldown",
            )
            self.restart.assert_not_called()

    def test_both_health_endpoints_are_checked_after_exception(self):
        opener = Mock()
        opener.open.side_effect = OSError("network private")
        with patch(
            "scripts.backend_watchdog.urllib.request.build_opener", return_value=opener
        ):
            self.assertFalse(probe_health())
        self.assertEqual(opener.open.call_count, 2)
        self.assertTrue(opener.open.call_args_list[1].args[0].endswith("/health/db"))

    def test_degraded_reports_with_http_200_does_not_restart_backend(self):
        response = MagicMock()
        response.status = 200
        response.read.side_effect = [
            b'{"status":"ok","reports_status":"degraded","reports_reason":"maintenance_mode"}',
            b'{"status":"ok","database":"connected"}',
        ]
        response.__enter__.return_value = response
        opener = Mock()
        opener.open.return_value = response
        with patch(
            "scripts.backend_watchdog.urllib.request.build_opener", return_value=opener
        ):
            self.assertEqual(self.tick(1000, healthy=probe_health()), "healthy")
        self.restart.assert_not_called()


class BackendHardeningTest(unittest.TestCase):
    def test_access_timestamp_is_iso8601_with_timezone_and_greppable(self):
        formatter = IsoAccessFormatter(
            "%(asctime)s %(request_line)s %(status_code)s", use_colors=False
        )
        record = logging.LogRecord(
            "uvicorn.access",
            logging.INFO,
            "",
            1,
            '%s - "%s %s HTTP/%s" %d',
            ("127.0.0.1:1", "GET", "/health", "1.1", 200),
            None,
        )
        output = formatter.format(record)
        timestamp = datetime.fromisoformat(output.split(" ", 1)[0])
        self.assertIsNotNone(timestamp.utcoffset())
        self.assertIn("GET /health HTTP/1.1", output)
        self.assertIn("200", output)

    def test_uvicorn_uses_explicit_selector_factory(self):
        config = create_config()
        factory = config.get_loop_factory()
        self.assertIsNotNone(factory)
        assert factory is not None
        loop = factory()
        try:
            self.assertIsInstance(loop, asyncio.SelectorEventLoop)
            self.assertEqual(config.limit_concurrency, 200)
            self.assertFalse(config.proxy_headers)
        finally:
            loop.close()

    def test_selector_serves_requests_on_isolated_socket(self):
        async def smoke():
            async def echo(reader, writer):
                writer.write(await reader.read(4))
                await writer.drain()
                writer.close()
                await writer.wait_closed()

            server = await asyncio.start_server(echo, "127.0.0.1", 0)
            async with server:
                for _ in range(2):
                    reader, writer = await asyncio.open_connection(
                        "127.0.0.1", server.sockets[0].getsockname()[1]
                    )
                    writer.write(b"ping")
                    await writer.drain()
                    self.assertEqual(await reader.read(4), b"ping")
                    writer.close()
                    await writer.wait_closed()

        with asyncio.Runner(loop_factory=asyncio.SelectorEventLoop) as runner:
            runner.run(smoke())
