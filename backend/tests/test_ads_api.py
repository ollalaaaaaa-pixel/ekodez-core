import time
import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from app.ads.api import ads_router
from app.models import Base
from app.security.tg_auth import SESSION_COOKIE, _signed_value


class AdsApiAuthorizationTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        app = FastAPI()
        app.include_router(ads_router(lambda: self.engine))
        self.client = TestClient(app)
        self.token_patch = patch.dict(
            "os.environ", {"TELEGRAM_BOT_TOKEN": "test-token"}, clear=False
        )
        self.token_patch.start()

    def tearDown(self):
        self.token_patch.stop()
        self.engine.dispose()

    def _cookie(self, role: str) -> str:
        return _signed_value({"role": role, "exp": int(time.time()) + 600}, "session")

    def test_all_ads_reads_are_owner_only(self):
        paths = (
            "/api/ads/metrics?start=2026-09-01&end=2026-09-30",
            "/api/ads/import-runs",
            "/api/ads/attribution-queue",
            "/api/ads/notifications",
            "/api/ads/notifications/unread-count",
        )
        for path in paths:
            with self.subTest(path=path):
                self.client.cookies.clear()
                self.assertEqual(self.client.get(path).status_code, 401)
                self.client.cookies.set(SESSION_COOKIE, self._cookie("master"))
                self.assertEqual(self.client.get(path).status_code, 403)
                self.client.cookies.set(SESSION_COOKIE, self._cookie("owner"))
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200)
                self.assertNotIn("phone", response.text.lower())

    def test_all_ads_writes_reject_anonymous_and_master(self):
        cases = (
            ("/api/ads/import?platform=2gis", None),
            ("/api/ads/leads/1/attribution", {"platform": "2gis"}),
            ("/api/ads/notifications/1/read", None),
        )
        for path, payload in cases:
            with self.subTest(path=path):
                self.client.cookies.clear()
                self.assertEqual(self.client.post(path, json=payload).status_code, 401)
                self.client.cookies.set(SESSION_COOKIE, self._cookie("master"))
                self.assertEqual(self.client.post(path, json=payload).status_code, 403)

    def test_metrics_reject_reversed_period(self):
        self.client.cookies.set(SESSION_COOKIE, self._cookie("owner"))
        response = self.client.get("/api/ads/metrics?start=2026-09-30&end=2026-09-01")
        self.assertEqual(response.status_code, 422)


if __name__ == "__main__":
    unittest.main()
