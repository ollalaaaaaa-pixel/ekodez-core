import hashlib
import hmac
import json
import os
import secrets
import time
from base64 import urlsafe_b64decode, urlsafe_b64encode
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal
from urllib.parse import parse_qsl

from fastapi import HTTPException, Request, Response
from sqlalchemy import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import ConsumedChallenge

AuthRole = Literal["owner", "master"]
MAX_INIT_DATA_AGE_SECONDS = 600
CHALLENGE_TTL_SECONDS = 300
SESSION_TTL_SECONDS = 12 * 60 * 60
CHALLENGE_COOKIE = "ekodez_auth_challenge"
SESSION_COOKIE = "ekodez_session"


class AuthenticationError(ValueError):
    pass


class RoleConfigurationError(AuthenticationError):
    pass


@dataclass(frozen=True)
class TelegramIdentity:
    telegram_user_id: int


@dataclass(frozen=True)
class AuthPrincipal:
    role: AuthRole


def verify_telegram_init_data(
    init_data: str,
    bot_token: str,
    *,
    now: int | None = None,
) -> TelegramIdentity:
    if not bot_token:
        raise AuthenticationError("Telegram authentication is not configured")
    pairs = dict(parse_qsl(init_data, keep_blank_values=True))
    received_hash = pairs.pop("hash", "")
    if not received_hash:
        raise AuthenticationError("Invalid Telegram authentication data")
    data_check_string = "\n".join(f"{key}={pairs[key]}" for key in sorted(pairs))
    secret = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    expected_hash = hmac.new(
        secret, data_check_string.encode(), hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(received_hash, expected_hash):
        raise AuthenticationError("Invalid Telegram authentication data")
    try:
        auth_date = int(pairs["auth_date"])
        user = json.loads(pairs["user"])
        telegram_user_id = int(user["id"])
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise AuthenticationError("Invalid Telegram authentication data") from error
    current = int(time.time()) if now is None else now
    if auth_date > current + 30 or current - auth_date > MAX_INIT_DATA_AGE_SECONDS:
        raise AuthenticationError("Telegram authentication data has expired")
    return TelegramIdentity(telegram_user_id=telegram_user_id)


def _numeric_id(name: str) -> int | None:
    value = os.getenv(name, "").strip()
    if not value.isdigit():
        return None
    return int(value)


def resolve_role(telegram_user_id: int) -> AuthRole:
    if telegram_user_id == _numeric_id("OWNER_TG_ID"):
        return "owner"
    if telegram_user_id == _numeric_id("ALEXEY_TG_ID"):
        return "master"
    raise RoleConfigurationError("Не удалось войти. Настройте роль Telegram в конфиге.")


def https_enabled() -> bool:
    return os.getenv("HTTPS_ENABLED", "").strip().lower() in {"1", "true", "yes"}


def _bot_token() -> str:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        raise AuthenticationError("Telegram authentication is not configured")
    return token


def _signing_key(purpose: str) -> bytes:
    return hmac.new(_bot_token().encode(), purpose.encode(), hashlib.sha256).digest()


def _b64encode(value: bytes) -> str:
    return urlsafe_b64encode(value).rstrip(b"=").decode()


def _b64decode(value: str) -> bytes:
    return urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _signed_value(payload: dict[str, object], purpose: str) -> str:
    body = _b64encode(json.dumps(payload, separators=(",", ":")).encode())
    signature = _b64encode(
        hmac.new(_signing_key(purpose), body.encode(), hashlib.sha256).digest()
    )
    return f"{body}.{signature}"


def _read_signed(value: str | None, purpose: str) -> dict[str, object] | None:
    if not value or "." not in value:
        return None
    body, received = value.split(".", 1)
    expected = _b64encode(
        hmac.new(_signing_key(purpose), body.encode(), hashlib.sha256).digest()
    )
    if not hmac.compare_digest(received, expected):
        return None
    try:
        parsed = json.loads(_b64decode(body))
    except (ValueError, json.JSONDecodeError):
        return None
    return parsed if isinstance(parsed, dict) else None


def _set_cookie(response: Response, name: str, value: str, max_age: int) -> None:
    response.set_cookie(
        name,
        value,
        max_age=max_age,
        httponly=True,
        secure=https_enabled(),
        samesite="strict",
        path="/",
    )


def issue_challenge(response: Response, *, now: int | None = None) -> str:
    current = int(time.time()) if now is None else now
    challenge = secrets.token_urlsafe(24)
    cookie = _signed_value(
        {"challenge": challenge, "exp": current + CHALLENGE_TTL_SECONDS},
        "challenge",
    )
    _set_cookie(response, CHALLENGE_COOKIE, cookie, CHALLENGE_TTL_SECONDS)
    return challenge


def authenticate_init_data(
    request: Request,
    response: Response,
    init_data: str,
    challenge: str,
    engine: Engine,
    *,
    now: int | None = None,
) -> AuthPrincipal:
    current = int(time.time()) if now is None else now
    response.delete_cookie(
        CHALLENGE_COOKIE, path="/", secure=https_enabled(), samesite="strict"
    )
    stored = _read_signed(request.cookies.get(CHALLENGE_COOKIE), "challenge")
    stored_challenge = stored.get("challenge") if stored else None
    stored_expiry = stored.get("exp") if stored else None
    if (
        stored is None
        or not isinstance(stored_challenge, str)
        or not hmac.compare_digest(stored_challenge, challenge)
        or not isinstance(stored_expiry, int)
        or stored_expiry < current
    ):
        raise AuthenticationError("Invalid or expired authentication challenge")
    identity = verify_telegram_init_data(init_data, _bot_token(), now=current)
    principal = AuthPrincipal(role=resolve_role(identity.telegram_user_id))
    session = _signed_value(
        {"role": principal.role, "exp": current + SESSION_TTL_SECONDS}, "session"
    )
    # Commit the unique hash before issuing a session: concurrent replays lose
    # at the database constraint, including across workers and process restarts.
    with Session(engine) as database:
        database.add(
            ConsumedChallenge(
                challenge_hash=hashlib.sha256(challenge.encode()).hexdigest(),
                consumed_at=datetime.fromtimestamp(current, UTC),
            )
        )
        try:
            database.commit()
        except IntegrityError as error:
            database.rollback()
            raise AuthenticationError(
                "Authentication challenge already consumed"
            ) from error
    _set_cookie(response, SESSION_COOKIE, session, SESSION_TTL_SECONDS)
    return principal


def principal_from_request(
    request: Request, *, now: int | None = None
) -> AuthPrincipal | None:
    role = signed_session_role(request, now=now)
    if role not in ("owner", "master"):
        return None
    return AuthPrincipal(role="owner" if role == "owner" else "master")


def signed_session_role(request: Request, *, now: int | None = None) -> str | None:
    """Return the role of a valid signed session before endpoint authorization."""
    try:
        stored = _read_signed(request.cookies.get(SESSION_COOKIE), "session")
    except AuthenticationError:
        return None
    if stored is None:
        return None
    current = int(time.time()) if now is None else now
    role = stored.get("role")
    expires = stored.get("exp")
    if (
        not isinstance(role, str)
        or not role
        or not isinstance(expires, int)
        or expires < current
    ):
        return None
    return role


def clear_session(response: Response) -> None:
    response.delete_cookie(
        SESSION_COOKIE, path="/", secure=https_enabled(), samesite="strict"
    )


def require_owner(request: Request) -> AuthPrincipal:
    principal = principal_from_request(request)
    if principal is None:
        raise HTTPException(status_code=401, detail="Требуется вход через Telegram")
    if principal.role != "owner":
        raise HTTPException(
            status_code=403, detail="Действие доступно только владельцу"
        )
    return principal


def require_reveal_access(
    request: Request,
    *,
    owner_only: bool = False,
) -> AuthPrincipal | None:
    client_host = request.client.host if request.client else ""
    is_localhost = client_host in ("127.0.0.1", "::1")
    if is_localhost and not owner_only:
        return None
    if not is_localhost and request.url.scheme != "https":
        raise HTTPException(
            status_code=426,
            detail="Для раскрытия данных с другого устройства требуется HTTPS",
        )
    principal = principal_from_request(request)
    if principal is None:
        raise HTTPException(status_code=401, detail="Требуется вход через Telegram")
    if owner_only and principal.role != "owner":
        raise HTTPException(
            status_code=403,
            detail="Реквизиты плательщика доступны только владельцу",
        )
    return principal
