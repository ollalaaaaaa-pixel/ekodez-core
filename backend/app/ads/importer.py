import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ads.attribution import attribute_lead
from app.ads.notifications import create_notification
from app.ads.parsers import AdsParseError, parse_ads_file
from app.models import AdCallLog, AdImportRun, AdSpend, Lead


@dataclass(frozen=True)
class ImportSummary:
    platform: str
    source_file: str
    rows: int
    period: str | None


def import_ads_file(
    session: Session,
    platform: str,
    path: Path,
    pii_key: str | None = None,
    now: datetime | None = None,
) -> ImportSummary:
    timestamp = now or datetime.now(UTC)
    filename = path.name
    file_sha256: str | None = None
    updated = 0
    try:
        file_sha256 = hashlib.sha256(path.read_bytes()).hexdigest()
        parsed = parse_ads_file(path, platform, pii_key=pii_key)
        for spend_item in parsed.spend_rows:
            row = session.scalar(
                select(AdSpend).where(
                    AdSpend.platform == platform,
                    AdSpend.campaign == spend_item.campaign,
                    AdSpend.period_start == spend_item.period_start,
                    AdSpend.period_end == spend_item.period_end,
                )
            )
            if row is None:
                row = AdSpend(
                    platform=platform,
                    campaign=spend_item.campaign,
                    period_start=spend_item.period_start,
                    period_end=spend_item.period_end,
                    spend=spend_item.spend,
                    impressions=spend_item.impressions,
                    clicks=spend_item.clicks,
                    conversions=spend_item.conversions,
                )
                session.add(row)
            else:
                updated += 1
                row.spend = spend_item.spend
                row.impressions = spend_item.impressions
                row.clicks = spend_item.clicks
                row.conversions = spend_item.conversions
                row.updated_at = timestamp
        for call_item in parsed.call_rows:
            exists = session.scalar(
                select(AdCallLog.id).where(
                    AdCallLog.platform == platform,
                    AdCallLog.call_date == call_item.call_date,
                    AdCallLog.phone_hash == call_item.phone_hash,
                    AdCallLog.source_file == filename,
                )
            )
            if exists is None:
                session.add(
                    AdCallLog(
                        platform=platform,
                        call_date=call_item.call_date,
                        phone_hash=call_item.phone_hash,
                        source_file=filename,
                    )
                )
        session.flush()
        for lead in session.scalars(
            select(Lead).where(Lead.attribution_method.is_(None))
        ):
            attribute_lead(session, lead, timestamp, pii_key=pii_key)
        all_dates = [row.period_start for row in parsed.spend_rows] + [
            row.call_date.date() for row in parsed.call_rows
        ]
        period = (
            f"{min(all_dates).isoformat()}..{max(all_dates).isoformat()}"
            if all_dates
            else None
        )
        count = len(parsed.spend_rows) + len(parsed.call_rows)
        session.add(
            AdImportRun(
                platform=platform,
                source_file=filename,
                file_sha256=file_sha256,
                status="ok",
                rows_imported=count,
                rows_updated=updated,
                period_start=min(all_dates) if all_dates else None,
                period_end=max(all_dates) if all_dates else None,
                created_at=timestamp,
            )
        )
        create_notification(
            session,
            "ads_import_ok",
            {
                "platform": platform,
                "source_file": filename,
                "rows": count,
                "period": period,
            },
            timestamp,
        )
        session.flush()
        return ImportSummary(platform, filename, count, period)
    except (AdsParseError, OSError, ValueError) as exc:
        session.rollback()
        reason = str(exc)[:300]
        session.add(
            AdImportRun(
                platform=platform,
                source_file=filename,
                file_sha256=file_sha256,
                status="error",
                error=reason,
                created_at=timestamp,
            )
        )
        create_notification(
            session,
            "ads_import_error",
            {"platform": platform, "source_file": filename, "reason": reason},
            timestamp,
        )
        session.flush()
        raise
