"""Legacy business-flow tests explicitly opt in, never read production config."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import maintenance


def enable_business_automation(test: unittest.TestCase) -> None:
    folder = tempfile.TemporaryDirectory(prefix="business-mode-test-")
    test.addCleanup(folder.cleanup)
    config = Path(folder.name) / "config.json"
    config.write_text('{"maintenance_mode":false}', encoding="utf-8")
    setting = patch.object(maintenance, "CONFIG_PATH", config)
    setting.start()
    test.addCleanup(setting.stop)
