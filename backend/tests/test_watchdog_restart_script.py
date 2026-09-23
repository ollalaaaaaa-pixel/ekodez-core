import os
import shutil
import subprocess
import tempfile
import time
import unittest
from pathlib import Path


@unittest.skipUnless(shutil.which("powershell.exe"), "Windows PowerShell required")
class RestartScriptTest(unittest.TestCase):
    def test_wrapper_records_previous_exit_and_process_last_line(self):
        source = (
            Path(__file__).resolve().parents[2]
            / "deployment/autostart/run-autostart-hidden.ps1"
        )
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "scripts").mkdir()
            (root / "logs").mkdir()
            target = root / "scripts/wrapper.ps1"
            shutil.copyfile(source, target)
            log = root / "logs/autostart-backend.log"
            log.write_text(
                "old WRAPPER START backend\nWinError 64\n"
                "old WRAPPER EXIT backend code=7\n"
            )
            command = (
                "function Start-Process { param($FilePath,$ArgumentList,$WindowStyle,"
                "[switch]$Wait,[switch]$PassThru) "
                "[pscustomobject]@{ExitCode=0} }; & '"
                + str(target).replace("'", "''")
                + "' -Service backend; exit $LASTEXITCODE"
            )
            result = subprocess.run(
                [
                    "powershell.exe",
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-Command",
                    command,
                ],
                capture_output=True,
                timeout=15,
            )
            self.assertEqual(result.returncode, 0)
            text = log.read_text()
            self.assertIn('"previous_exit_code":"7"', text)
            self.assertIn('"previous_last_line":"WinError 64"', text)

    def simulate(self, scenario):
        script = (
            Path(__file__).resolve().parents[2]
            / "deployment/autostart/restart-backend.ps1"
        )
        fixture = Path(__file__).parent / "fixtures/watchdog_restart_mock.ps1"
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "logs").mkdir()
            (root / "logs/autostart-backend.log").write_text(
                "old WRAPPER START backend\n"
            )
            if scenario in {"deploy", "deploy_explicit"}:
                (root / "deploy-in-progress").touch()
            if scenario == "stale":
                lock = root / "logs/backend-restart.lock"
                lock.touch()
                old = time.time() - 7200
                os.utime(lock, (old, old))
            result = subprocess.run(
                [
                    "powershell.exe",
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(fixture),
                    "-Root",
                    folder,
                    "-Script",
                    str(script),
                    "-Scenario",
                    scenario,
                ],
                capture_output=True,
                timeout=15,
                check=False,
            )
            actions = root / "actions.txt"
            self.last_log = (root / "logs/autostart-backend.log").read_text()
            self.last_stderr = result.stderr.decode(errors="replace")
            self.last_lock_exists = (root / "logs/backend-restart.lock").exists()
            return result.returncode, (
                actions.read_text().splitlines() if actions.exists() else []
            )

    def test_verified_process_restart_order_and_both_probes(self):
        code, actions = self.simulate("normal")
        self.assertEqual(code, 0)
        self.assertEqual(
            actions,
            [
                "stop:EkodezBackend",
                "kill:99999",
                "start:EkodezBackend",
                "probe:http://127.0.0.1:8000/health",
                "probe:http://127.0.0.1:8000/health/db",
            ],
        )

    def test_foreign_port_owner_prevents_all_mutations(self):
        code, actions = self.simulate("foreign")
        self.assertNotEqual(code, 0)
        self.assertEqual(actions, [])

    def test_pid_reuse_prevents_kill_but_restarts_stopped_task(self):
        code, actions = self.simulate("reused")
        self.assertNotEqual(code, 0)
        self.assertEqual(actions.count("stop:EkodezBackend"), 1)
        self.assertNotIn("kill:99999", actions)
        self.assertEqual(actions.count("start:EkodezBackend"), 1)

    def test_other_process_owner_prevents_all_mutations(self):
        code, actions = self.simulate("otherowner")
        self.assertNotEqual(code, 0)
        self.assertEqual(actions, [])

    def test_real_deploy_flag_prevents_all_mutations(self):
        code, actions = self.simulate("deploy")
        self.assertEqual(code, 20)
        self.assertEqual(actions, [])

    def test_explicit_deployment_uses_same_restart_lock(self):
        code, actions = self.simulate("deploy_explicit")
        self.assertEqual(code, 0)
        self.assertEqual(actions.count("stop:EkodezBackend"), 1)
        self.assertEqual(actions.count("start:EkodezBackend"), 1)
        self.assertEqual(len([a for a in actions if a.startswith("probe:")]), 2)
        self.assertFalse(self.last_lock_exists)

    def test_flag_after_stop_still_starts_backend_and_checks_health(self):
        code, actions = self.simulate("flag_after_stop")
        self.assertEqual(code, 0)
        self.assertEqual(
            actions,
            [
                "stop:EkodezBackend",
                "kill:99999",
                "start:EkodezBackend",
                "probe:http://127.0.0.1:8000/health",
                "probe:http://127.0.0.1:8000/health/db",
            ],
        )
        self.assertIn("warning=deploy_flag_during_restart", self.last_log)
        self.assertFalse(self.last_lock_exists)

    def test_unavailable_log_does_not_interrupt_restart_or_health(self):
        code, actions = self.simulate("log_unavailable")
        self.assertEqual(code, 0, self.last_stderr)
        self.assertEqual(
            actions,
            [
                "stop:EkodezBackend",
                "kill:99999",
                "start:EkodezBackend",
                "probe:http://127.0.0.1:8000/health",
                "probe:http://127.0.0.1:8000/health/db",
            ],
        )
        self.assertIn("log_write_failed", self.last_stderr)
        self.assertIn("deploy_flag_during_restart", self.last_stderr)
        self.assertFalse(self.last_lock_exists)

    def test_stale_restart_lock_is_removed_before_starting(self):
        code, actions = self.simulate("stale")
        self.assertEqual(code, 0)
        self.assertEqual(actions.count("start:EkodezBackend"), 1)
        self.assertIn("warning=stale_restart_lock", self.last_log)
        self.assertFalse(self.last_lock_exists)

    def test_parallel_restart_has_one_owner_and_second_is_lock_busy(self):
        script = (
            Path(__file__).resolve().parents[2]
            / "deployment/autostart/restart-backend.ps1"
        )
        fixture = Path(__file__).parent / "fixtures/watchdog_restart_mock.ps1"
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "logs").mkdir()
            (root / "logs/autostart-backend.log").write_text(
                "old WRAPPER START backend\n"
            )
            args = [
                "powershell.exe",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(fixture),
                "-Root",
                folder,
                "-Script",
                str(script),
                "-Scenario",
                "hold_lock",
            ]
            first = subprocess.Popen(
                args, stdout=subprocess.PIPE, stderr=subprocess.PIPE
            )
            try:
                lock = root / "logs/backend-restart.lock"
                for _ in range(100):
                    if lock.exists():
                        break
                    time.sleep(0.02)
                self.assertTrue(lock.exists(), "first process did not acquire lock")
                second = subprocess.run(args, capture_output=True, timeout=15)
                (root / "release-first-restart").touch()
                first.communicate(timeout=15)
                self.assertEqual(first.returncode, 0)
                self.assertEqual(second.returncode, 21)
                actions = (root / "actions.txt").read_text().splitlines()
                self.assertEqual(actions.count("stop:EkodezBackend"), 1)
                self.assertEqual(actions.count("kill:99999"), 1)
                self.assertEqual(actions.count("start:EkodezBackend"), 1)
            finally:
                (root / "release-first-restart").touch()
                if first.poll() is None:
                    first.kill()
                    first.communicate(timeout=5)
