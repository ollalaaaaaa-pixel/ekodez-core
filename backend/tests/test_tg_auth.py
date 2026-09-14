import hashlib
import hmac
import json
import time
import unittest
from unittest.mock import patch
from urllib.parse import urlencode

from app.security.tg_auth import (
    AuthenticationError,
    RoleConfigurationError,
    resolve_role,
    verify_telegram_init_data,
)

BOT_TOKEN = "synthetic-bot-token"


def signed_init_data(user_id: int, *, auth_date: int, token: str = BOT_TOKEN) -> str:
    values = {
        "auth_date": str(auth_date),
        "query_id": "synthetic-query",
        "user": json.dumps(
            {"id": user_id, "first_name": "Test"}, separators=(",", ":")
        ),
    }
    data_check_string = "\n".join(f"{key}={values[key]}" for key in sorted(values))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    values["hash"] = hmac.new(
        secret, data_check_string.encode(), hashlib.sha256
    ).hexdigest()
    return urlencode(values)


class TelegramInitDataTests(unittest.TestCase):
    def test_valid_init_data_returns_numeric_identity(self):
        now = int(time.time())

        identity = verify_telegram_init_data(
            signed_init_data(101, auth_date=now), BOT_TOKEN, now=now
        )

        self.assertEqual(identity.telegram_user_id, 101)

    def test_tampered_init_data_is_rejected(self):
        now = int(time.time())
        tampered = signed_init_data(101, auth_date=now).replace(
            "synthetic-query", "changed"
        )

        with self.assertRaises(AuthenticationError):
            verify_telegram_init_data(tampered, BOT_TOKEN, now=now)

    def test_stale_init_data_is_rejected(self):
        now = int(time.time())

        with self.assertRaises(AuthenticationError):
            verify_telegram_init_data(
                signed_init_data(101, auth_date=now - 601), BOT_TOKEN, now=now
            )

    def test_roles_are_resolved_only_from_numeric_configured_ids(self):
        with patch.dict(
            "os.environ", {"OWNER_TG_ID": "101", "ALEXEY_TG_ID": "202"}, clear=False
        ):
            self.assertEqual(resolve_role(101), "owner")
            self.assertEqual(resolve_role(202), "master")

    def test_unconfigured_identity_gets_generic_configuration_error(self):
        with (
            patch.dict(
                "os.environ", {"OWNER_TG_ID": "101", "ALEXEY_TG_ID": ""}, clear=False
            ),
            self.assertRaisesRegex(
                RoleConfigurationError, "Настройте роль Telegram в конфиге"
            ),
        ):
            resolve_role(303)


if __name__ == "__main__":
    unittest.main()
