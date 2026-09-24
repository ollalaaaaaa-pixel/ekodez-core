import json
import tempfile
import unittest
from pathlib import Path

from app.ads.config import AdsConfigError, load_ads_config


class AdsConfigTest(unittest.TestCase):
    def test_defaults_and_nullable_thresholds(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config_path = root / "config.json"
            config_path.write_text(
                json.dumps(
                    {
                        "root": str(root),
                        "platforms": {"yandex_direct": {"mode": "manual"}},
                    }
                ),
                encoding="utf-8",
            )

            config = load_ads_config(config_path)

            platform = config.platforms["yandex_direct"]
            self.assertEqual(platform.reminder_period_days, 7)
            self.assertIsNone(platform.target_cpl)
            self.assertIsNone(platform.zero_lead_spend_threshold)

    def test_unknown_platform_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config_path = root / "config.json"
            config_path.write_text(
                json.dumps({"root": str(root), "platforms": {"unknown": {}}}),
                encoding="utf-8",
            )

            with self.assertRaises(AdsConfigError):
                load_ads_config(config_path)


if __name__ == "__main__":
    unittest.main()
