import re
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AdCallLog, Lead
from app.security.ad_phone_hash import PhoneHashError, phone_hmac
from app.security.pii import decrypt_pii

UTM_ALIASES = {
    "yandex": "yandex_direct",
    "yandex_direct": "yandex_direct",
    "direct": "yandex_direct",
    "yandex_business": "yandex_business",
    "yandex_maps": "yandex_business",
    "2gis": "2gis",
    "2gis.ru": "2gis",
}


@dataclass(frozen=True)
class AttributionResult:
    platform: str | None
    method: str | None
    disputed: bool = False


def attribute_lead(
    session: Session, lead: Lead, now: datetime, pii_key: str | None = None
) -> AttributionResult:
    if lead.attribution_method == "manual":
        return AttributionResult(lead.attributed_platform, "manual")
    alias = UTM_ALIASES.get((lead.utm_source or "").strip().lower())
    if alias:
        lead.attributed_platform = alias
        lead.attribution_method = "utm"
        lead.attributed_at = now
        return AttributionResult(alias, "utm")
    try:
        phone = decrypt_pii(lead.encrypted_pii).get("phone")
        digests = {
            phone_hmac(item, key=pii_key)
            for item in re.split(r"\s*;\s*", phone or "")
            if item.strip()
        }
    except (ValueError, PhoneHashError):
        return AttributionResult(None, None)
    if not digests:
        return AttributionResult(None, None)
    center = lead.order_at or lead.created_at
    matches = session.scalars(
        select(AdCallLog).where(
            AdCallLog.phone_hash.in_(digests),
            AdCallLog.call_date >= center - timedelta(days=7),
            AdCallLog.call_date <= center + timedelta(days=7),
        )
    ).all()
    platforms = {row.platform for row in matches}
    if len(platforms) != 1:
        return AttributionResult(None, None, disputed=len(platforms) > 1)
    platform = platforms.pop()
    lead.attributed_platform = platform
    lead.attribution_method = "phone_match"
    lead.attributed_at = now
    return AttributionResult(platform, "phone_match")


def set_manual_attribution(
    session: Session, lead: Lead, platform: str | None, now: datetime
) -> None:
    lead.attributed_platform = platform
    lead.attribution_method = "manual"
    lead.attributed_at = now
    session.flush()
