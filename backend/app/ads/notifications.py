import hashlib
import re
from datetime import datetime
from pathlib import Path

from sqlalchemy.orm import Session

from app.models import Notification

ALLOWED_PAYLOAD_FIELDS = {
    "ads_import_ok": {"platform", "source_file", "rows", "period"},
    "ads_import_error": {"platform", "source_file", "reason"},
    "ads_upload_reminder": {"platform", "folder", "instructions", "period_key"},
    "ads_alert": {"platform", "reason", "period", "metrics"},
    "draft_ready": {"platform", "draft_path", "period"},
    "ads_delivery_failed": {"reason", "period"},
}

_PLATFORMS = {"yandex_direct", "yandex_business", "2gis"}
_SAFE_FILE = re.compile(r"^file-[0-9a-f]{12}(?:\.(?:csv|xlsx|xls|md))?$")
_SAFE_PERIOD = re.compile(
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}(?:\.\.|-)[0-9]{4}-[0-9]{2}-[0-9]{2}$"
)
_METRIC_FIELDS = {"spend", "leads", "revenue", "cpl", "romi"}


def _masked_file(value: object) -> str:
    text = str(value)
    if _SAFE_FILE.fullmatch(text):
        return text
    suffix = Path(text).suffix.lower()
    if suffix not in {".csv", ".xlsx", ".xls", ".md"}:
        suffix = ""
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]
    return f"file-{digest}{suffix}"


def _safe_value(kind: str, key: str, value: object, platform: str) -> object:
    if key == "platform":
        return value if isinstance(value, str) and value in _PLATFORMS else "other"
    if key in {"source_file", "draft_path"}:
        return _masked_file(value)
    if key == "folder":
        return f"ads/{platform}"
    if key == "reason":
        if kind == "ads_import_error":
            return "Ошибка импорта"
        if kind == "ads_delivery_failed":
            return "Не удалось доставить недельную сводку"
        return "CPL/нулевые лиды"
    if key in {"period", "period_key"}:
        text = str(value)
        return text if _SAFE_PERIOD.fullmatch(text) else "скрыто"
    if key == "metrics" and isinstance(value, dict):
        result: dict[str, object] = {}
        for metric, item in value.items():
            if metric not in _METRIC_FIELDS:
                continue
            if metric == "leads" and isinstance(item, int):
                result[metric] = max(0, item)
            elif item is None or (
                isinstance(item, str) and re.fullmatch(r"-?[0-9]+(?:\.[0-9]{2})?", item)
            ):
                result[metric] = item
        return result
    if key == "instructions" and isinstance(value, list):
        allowed = {
            "расход, показы и клики по кампаниям",
            "конверсии и звонки",
            "период отчета",
        }
        return [item for item in value if item in allowed]
    if key == "rows":
        return max(0, int(value)) if isinstance(value, (int, str)) else 0
    return value


def create_notification(
    session: Session, kind: str, payload: dict[str, object], now: datetime
) -> Notification:
    allowed = ALLOWED_PAYLOAD_FIELDS.get(kind)
    if allowed is None:
        raise ValueError("unsupported notification kind")
    platform_value = payload.get("platform")
    platform = (
        platform_value
        if isinstance(platform_value, str) and platform_value in _PLATFORMS
        else "other"
    )
    safe_payload = {
        key: _safe_value(kind, key, value, platform)
        for key, value in payload.items()
        if key in allowed
    }
    row = Notification(kind=kind, payload=safe_payload, created_at=now)
    session.add(row)
    session.flush()
    return row
