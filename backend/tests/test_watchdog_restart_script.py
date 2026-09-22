import shutil
import subprocess
import tempfile
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
            if scenario == "deploy":
                (root / "deploy-in-progress").touch()
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

    def test_pid_reuse_prevents_kill_and_start(self):
        code, actions = self.simulate("reused")
        self.assertNotEqual(code, 0)
        self.assertEqual(actions, ["stop:EkodezBackend"])

    def test_other_process_owner_prevents_all_mutations(self):
        code, actions = self.simulate("otherowner")
        self.assertNotEqual(code, 0)
        self.assertEqual(actions, [])

    def test_real_deploy_flag_prevents_all_mutations(self):
        code, actions = self.simulate("deploy")
        self.assertEqual(code, 20)
        self.assertEqual(actions, [])
