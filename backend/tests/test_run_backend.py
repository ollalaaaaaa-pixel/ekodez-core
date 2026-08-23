import unittest

from scripts.run_backend import create_config


class BackendLaunchConfigTest(unittest.TestCase):
    def test_proxy_headers_are_disabled(self):
        config = create_config()
        self.assertFalse(config.proxy_headers)
        self.assertEqual(config.host, "127.0.0.1")


if __name__ == "__main__":
    unittest.main()
