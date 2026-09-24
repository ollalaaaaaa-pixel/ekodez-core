import hashlib
import hmac
import os
import re


class PhoneHashError(ValueError):
    """Raised when a phone or the PII key cannot be used safely."""


def _canonical_phone(phone: str) -> str:
    digits = re.sub(r"\D", "", phone)
    if len(digits) == 10:
        digits = f"7{digits}"
    elif len(digits) == 11 and digits.startswith("8"):
        digits = f"7{digits[1:]}"
    if len(digits) != 11 or not digits.startswith("7"):
        raise PhoneHashError("invalid Russian phone")
    return digits


def phone_hmac(phone: str, key: str | None = None) -> str:
    secret = (key if key is not None else os.getenv("PII_FERNET_KEY", "")).strip()
    if not secret:
        raise PhoneHashError("PII key is not configured")
    derived_key = hmac.new(
        secret.encode("utf-8"),
        b"ekodez-ad-phone-v1",
        hashlib.sha256,
    ).digest()
    return hmac.new(
        derived_key,
        _canonical_phone(phone).encode("ascii"),
        hashlib.sha256,
    ).hexdigest()
