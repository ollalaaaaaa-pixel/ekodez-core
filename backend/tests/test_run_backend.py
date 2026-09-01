import unittest

from scripts.run_backend import create_config


class BackendLaunchConfigTest(unittest.TestCase):
    def test_backend_listens_on_lan_without_proxy_headers(self):
        config = create_config()
        self.assertFalse(config.proxy_headers)
        self.assertEqual(config.host, "0.0.0.0")


if __name__ == "__main__":
    unittest.main()
