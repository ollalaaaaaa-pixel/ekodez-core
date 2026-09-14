import io
import json
import os
import time
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from app import main
from app.models import Base
from tests.auth_helpers import login_telegram, signed_init_data

TOKEN = "synthetic-api-bot-token"
TEST_PHONE_1 = "8921" + "0000000"
TEST_PHONE_2 = "8921" + "0000001"


class TelegramAuthApiTests(unittest.TestCase):
    def setUp(self):
        self.original_engine = main.engine
        self.engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        main.engine = self.engine
        self.environment = patch.dict(
            os.environ,
            {
                "TELEGRAM_BOT_TOKEN": TOKEN,
                "OWNER_TG_ID": "101",
                "ALEXEY_TG_ID": "202",
                "PII_FERNET_KEY": Fernet.generate_key().decode("ascii"),
                "HTTPS_ENABLED": "0",
            },
            clear=False,
        )
        self.environment.start()

    def tearDown(self):
        self.environment.stop()
        main.engine = self.original_engine
        self.engine.dispose()

    def test_challenge_is_audited_without_secret_and_owner_session_is_created(self):
        output = io.StringIO()
        client = TestClient(main.app, client=("192.168.1.20", 51000))
        with redirect_stdout(output):
            challenge = client.post("/api/auth/challenge")
        self.assertEqual(challenge.status_code, 200, challenge.text)
        raw_challenge = challenge.json()["challenge"]
        audit = json.loads(output.getvalue())
        self.assertEqual(audit["event"], "challenge_issued")
        self.assertNotIn(raw_challenge, output.getvalue())
        self.assertNotIn("101", output.getvalue())

        result = login_telegram(client, 101, TOKEN)
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.json(), {"role": "owner"})
        current = client.get("/api/auth/session")
        self.assertEqual(current.json(), {"authenticated": True, "role": "owner"})
        client.close()

    def test_unknown_identity_gets_configuration_message_and_no_session(self):
        client = TestClient(main.app, client=("192.168.1.20", 51000))
        result = login_telegram(client, 303, TOKEN)
        self.assertEqual(result.status_code, 403)
        self.assertEqual(
            result.json()["detail"],
            "Не удалось войти. Настройте роль Telegram в конфиге.",
        )
        self.assertEqual(
            client.get("/api/auth/session").json(),
            {"authenticated": False, "role": None},
        )
        client.close()

    def test_challenge_cannot_be_reused(self):
        client = TestClient(main.app)
        challenge = client.post("/api/auth/challenge").json()["challenge"]
        payload = {
            "init_data": signed_init_data(101, TOKEN),
            "challenge": challenge,
        }
        first = client.post("/api/auth/telegram", json=payload)
        second = client.post("/api/auth/telegram", json=payload)
        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 401)
        client.close()

    def test_secure_cookie_follows_https_configuration(self):
        with patch.dict(os.environ, {"HTTPS_ENABLED": "1"}, clear=False):
            client = TestClient(main.app, base_url="https://crm.test")
            challenge = client.post("/api/auth/challenge")
            self.assertIn("Secure", challenge.headers["set-cookie"])
            client.close()

    def test_expired_session_is_rejected(self):
        client = TestClient(main.app)
        self.assertEqual(login_telegram(client, 101, TOKEN).status_code, 200)
        with patch(
            "app.security.tg_auth.time.time",
            return_value=time.time() + (13 * 60 * 60),
        ):
            current = client.get("/api/auth/session")
        self.assertEqual(current.json(), {"authenticated": False, "role": None})
        client.close()

    def test_localhost_reveal_works_but_remote_http_reveal_requires_https(self):
        lead = main.ingest_lead(
            main.RawTextIn(
                text=(
                    "id сделки: auth-1\nИмя клиента: Тест Клиент\n"
                    f"Телефон: {TEST_PHONE_1}\n"
                    "Адрес: г. Архангельск, ул. Тестовая, 1"
                )
            )
        )
        local = TestClient(main.app, client=("127.0.0.1", 51000))
        self.assertEqual(
            local.get(f"/api/leads/{lead.id}?show_pii=true").status_code, 200
        )
        local.close()

        remote = TestClient(main.app, client=("192.168.1.20", 51000))
        self.assertEqual(login_telegram(remote, 101, TOKEN).status_code, 200)
        blocked = remote.get(f"/api/leads/{lead.id}?show_pii=true")
        self.assertEqual(blocked.status_code, 426)
        remote.close()

    def test_authenticated_master_can_reveal_lead_over_https(self):
        lead = main.ingest_lead(
            main.RawTextIn(
                text=(
                    "id сделки: auth-2\nИмя клиента: Тест Мастер\n"
                    f"Телефон: {TEST_PHONE_2}\n"
                    "Адрес: г. Архангельск, ул. Тестовая, 2"
                )
            )
        )
        remote = TestClient(
            main.app,
            base_url="https://crm.test",
            client=("192.168.1.20", 51000),
        )
        with patch.dict(os.environ, {"HTTPS_ENABLED": "1"}, clear=False):
            self.assertEqual(login_telegram(remote, 202, TOKEN).status_code, 200)
            revealed = remote.get(f"/api/leads/{lead.id}?show_pii=true")
        self.assertEqual(revealed.status_code, 200, revealed.text)
        self.assertEqual(revealed.headers["cache-control"], "no-store")
        remote.close()


if __name__ == "__main__":
    unittest.main()
