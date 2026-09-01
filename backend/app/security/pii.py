import json
import os
import re
from collections.abc import Mapping
from typing import Any

from cryptography.fernet import Fernet, InvalidToken

PII_FIELDS = ("client_name", "phone", "address", "comment", "raw_text")


def mask_phone(value: str | None) -> str:
    digits = re.sub(r"\D", "", value or "")
    if not digits:
        return ""
    if len(digits) < 8:
        return "***"
    return f"{digits[:4]}***{digits[-4:]}"


def mask_address(value: str | None) -> str:
    address = (value or "").strip()
    if not address:
        return ""
    city = address.split(",", 1)[0].strip()
    if "," not in address:
        street_marker = re.search(
            r"\s+(?:ул(?:ица)?\.?|проспект|пр-т|пер(?:еулок)?\.?|"
            r"наб(?:ережная)?\.?|шоссе|дом|д\.)\s+",
            address,
            re.IGNORECASE,
        )
        if street_marker:
            city = address[: street_marker.start()].strip()
    return f"{city}, ***"


def mask_name(value: str | None) -> str:
    parts = (value or "").split()
    if not parts:
        return ""
    if len(parts) >= 3:
        return parts[1]
    if len(parts) == 2 and re.search(
        r"(?:ов|ова|ев|ева|ин|ина|ский|ская)$", parts[0], re.IGNORECASE
    ):
        return parts[1]
    return parts[0]


def mask_text(
    value: str | None,
    *,
    name: str | None,
    phone: str | None,
    address: str | None,
    comment: str | None = None,
) -> str:
    masked = value or ""
    replacements = (
        (comment, "***"),
        (address, mask_address(address)),
        (phone, mask_phone(phone)),
        (name, mask_name(name)),
    )
    for original, replacement in replacements:
        if original:
            masked = re.sub(
                re.escape(original), replacement, masked, flags=re.IGNORECASE
            )
    masked = re.sub(
        r"(?<!\d)(?:\+?7|8)[\s()\-]*\d{3}[\s()\-]*\d{3}"
        r"[\s()\-]*\d{2}[\s()\-]*\d{2}(?!\d)",
        lambda match: mask_phone(match.group(0)),
        masked,
    )
    return masked


def _fernet() -> Fernet | None:
    key = os.getenv("PII_FERNET_KEY", "").strip()
    if not key:
        return None
    try:
        return Fernet(key.encode("ascii"))
    except (ValueError, UnicodeEncodeError):
        return None


def pii_status() -> str:
    return "ok" if _fernet() is not None else "degraded"


def encrypt_pii(values: Mapping[str, Any]) -> str | None:
    fernet = _fernet()
    if fernet is None:
        return None
    payload = {field: values.get(field) for field in PII_FIELDS}
    encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    return fernet.encrypt(encoded).decode("ascii")


def encrypt_sensitive_mapping(values: Mapping[str, Any]) -> str | None:
    fernet = _fernet()
    if fernet is None:
        return None
    encoded = json.dumps(dict(values), ensure_ascii=False).encode("utf-8")
    return fernet.encrypt(encoded).decode("ascii")


def decrypt_pii(token: str | None) -> dict[str, str | None]:
    fernet = _fernet()
    if fernet is None or not token:
        raise ValueError("PII is unavailable")
    try:
        decoded = fernet.decrypt(token.encode("ascii"))
        payload = json.loads(decoded.decode("utf-8"))
    except (InvalidToken, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError("PII is unavailable") from error
    return {
        field: value if isinstance(value, str) or value is None else str(value)
        for field in PII_FIELDS
        for value in (payload.get(field),)
    }


def decrypt_sensitive_mapping(token: str | None) -> dict[str, str | None]:
    fernet = _fernet()
    if fernet is None or not token:
        raise ValueError("PII is unavailable")
    try:
        decoded = fernet.decrypt(token.encode("ascii"))
        payload = json.loads(decoded.decode("utf-8"))
    except (InvalidToken, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError("PII is unavailable") from error
    if not isinstance(payload, dict):
        raise ValueError("PII is unavailable")
    return {
        str(field): value if isinstance(value, str) or value is None else str(value)
        for field, value in payload.items()
    }


def protect_lead_pii(values: Mapping[str, Any], raw_text: str) -> dict[str, Any]:
    full_pii = {
        "client_name": values.get("client_name") or None,
        "phone": values.get("phone") or None,
        "address": values.get("address") or None,
        "comment": values.get("comment") or None,
        "raw_text": raw_text,
    }
    protected = dict(values)
    protected.update(
        client_name=mask_name(full_pii["client_name"]) or None,
        phone=mask_phone(full_pii["phone"]) or None,
        address=mask_address(full_pii["address"]) or None,
        comment="***" if full_pii["comment"] else None,
        raw_text=mask_text(
            raw_text,
            name=full_pii["client_name"],
            phone=full_pii["phone"],
            address=full_pii["address"],
            comment=full_pii["comment"],
        ),
        encrypted_pii=encrypt_pii(full_pii),
    )
    return protected
