from datetime import datetime

from sqlalchemy.orm import Session

from app.models import Notification

ALLOWED_PAYLOAD_FIELDS = {
    "ads_import_ok": {"platform", "source_file", "rows", "period"},
    "ads_import_error": {"platform", "source_file", "reason"},
    "ads_upload_reminder": {"platform", "folder", "instructions", "period_key"},
    "ads_alert": {"platform", "reason", "period", "metrics"},
    "draft_ready": {"platform", "draft_path", "period"},
}


def create_notification(
    session: Session, kind: str, payload: dict[str, object], now: datetime
) -> Notification:
    allowed = ALLOWED_PAYLOAD_FIELDS.get(kind)
    if allowed is None:
        raise ValueError("unsupported notification kind")
    safe_payload = {key: value for key, value in payload.items() if key in allowed}
    row = Notification(kind=kind, payload=safe_payload, created_at=now)
    session.add(row)
    session.flush()
    return row
