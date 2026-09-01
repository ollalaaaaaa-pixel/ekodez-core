import unittest

from fastapi.testclient import TestClient

from app import main


class LanCorsTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main.app)

    def test_private_lan_frontend_origin_is_allowed(self):
        response = self.client.options(
            "/health",
            headers={
                "Origin": "http://192.168.1.42:5173",
                "Access-Control-Request-Method": "GET",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.headers.get("access-control-allow-origin"),
            "http://192.168.1.42:5173",
        )

    def test_public_origin_is_not_allowed(self):
        response = self.client.options(
            "/health",
            headers={
                "Origin": "http://example.com:5173",
                "Access-Control-Request-Method": "GET",
            },
        )

        self.assertNotEqual(
            response.headers.get("access-control-allow-origin"),
            "http://example.com:5173",
        )


if __name__ == "__main__":
    unittest.main()
