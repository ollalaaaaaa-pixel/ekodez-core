import hashlib
import hmac
import json
import time
from typing import Any, Protocol
from urllib.parse import urlencode

from fastapi.testclient import TestClient


class TestResponse(Protocol):
    @property
    def status_code(self) -> int: ...

    @property
    def text(self) -> str: ...

    def json(self) -> Any: ...


def signed_init_data(user_id: int, token: str) -> str:
    values = {
        "auth_date": str(int(time.time())),
        "query_id": "synthetic-api-query",
        "user": json.dumps(
            {"id": user_id, "first_name": "Test"}, separators=(",", ":")
        ),
    }
    check = "\n".join(f"{key}={values[key]}" for key in sorted(values))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    values["hash"] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return urlencode(values)


def login_telegram(client: TestClient, user_id: int, token: str) -> TestResponse:
    challenge_response = client.post("/api/auth/challenge")
    if challenge_response.status_code != 200:
        return challenge_response
    return client.post(
        "/api/auth/telegram",
        json={
            "init_data": signed_init_data(user_id, token),
            "challenge": challenge_response.json()["challenge"],
        },
    )
