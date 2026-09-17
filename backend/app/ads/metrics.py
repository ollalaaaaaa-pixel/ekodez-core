from dataclasses import asdict, dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import AdSpend, Lead, Transaction


@dataclass(frozen=True)
class MetricRow:
    platform: str
    campaign: str
    spend: Decimal
    leads: int
    revenue: Decimal
    cpl: Decimal | None
    romi: Decimal | None
    cpl_reason: str | None = None
    romi_reason: str | None = None

    def json(self) -> dict[str, object]:
        data = asdict(self)
        for key in ("spend", "revenue", "cpl", "romi"):
            value = data[key]
            data[key] = None if value is None else f"{value:.2f}"
        return data


def _lead_ids(
    session: Session, platform: str, campaign: str | None, start: date, end: date
) -> list[int]:
    query = select(Lead.id).where(
        Lead.attributed_platform == platform,
        func.date(Lead.created_at) >= start,
        func.date(Lead.created_at) <= end,
    )
    query = (
        query.where(Lead.utm_campaign.is_(None))
        if campaign is None
        else query.where(Lead.utm_campaign == campaign)
    )
    return list(session.scalars(query))


def _revenue(
    session: Session, platform: str, campaign: str | None, start: date, end: date
) -> Decimal:
    query = (
        select(func.coalesce(func.sum(Transaction.amount), 0))
        .join(Lead, Transaction.lead_id == Lead.id)
        .where(
            Transaction.kind == "income",
            Transaction.operation_date >= start,
            Transaction.operation_date <= end,
            Lead.attributed_platform == platform,
        )
    )
    query = (
        query.where(Lead.utm_campaign.is_(None))
        if campaign is None
        else query.where(Lead.utm_campaign == campaign)
    )
    return Decimal(session.scalar(query) or 0).quantize(Decimal("0.01"))


def _row(
    session: Session,
    platform: str,
    campaign: str | None,
    spend: Decimal,
    start: date,
    end: date,
) -> MetricRow:
    leads = len(_lead_ids(session, platform, campaign, start, end))
    revenue = _revenue(session, platform, campaign, start, end)
    cpl: Decimal | None = None
    romi: Decimal | None = None
    cpl_reason: str | None = None
    romi_reason: str | None = None
    if not spend:
        cpl_reason = "no_spend"
        romi_reason = "no_spend"
    elif not leads and not revenue:
        cpl_reason = "no_attributed_leads"
        romi_reason = "no_attributed_leads"
    else:
        if leads:
            cpl = (spend / leads).quantize(Decimal("0.01"))
        else:
            cpl_reason = "no_attributed_leads"
        if not revenue:
            romi_reason = "no_income_transactions"
        else:
            romi = ((revenue - spend) / spend * 100).quantize(Decimal("0.01"))
    return MetricRow(
        platform=platform,
        campaign=campaign or "Без кампании",
        spend=spend,
        leads=leads,
        revenue=revenue,
        cpl=cpl,
        romi=romi,
        cpl_reason=cpl_reason,
        romi_reason=romi_reason,
    )


def ads_metrics(session: Session, start: date, end: date) -> list[MetricRow]:
    spends = session.scalars(
        select(AdSpend).where(AdSpend.period_start <= end, AdSpend.period_end >= start)
    ).all()
    grouped: dict[tuple[str, str], Decimal] = {}
    for spend_row in spends:
        key = (spend_row.platform, spend_row.campaign)
        total_days = (spend_row.period_end - spend_row.period_start).days + 1
        overlap_start = max(start, spend_row.period_start)
        overlap_end = min(end, spend_row.period_end)
        overlap_days = (overlap_end - overlap_start).days + 1
        full_spend = Decimal(spend_row.spend or 0)
        apportioned = (full_spend * overlap_days / total_days).quantize(Decimal("0.01"))
        grouped[key] = grouped.get(key, Decimal("0.00")) + apportioned

    attributed = session.execute(
        select(Lead.attributed_platform, Lead.utm_campaign).where(
            Lead.attributed_platform.is_not(None),
            func.date(Lead.created_at) >= start,
            func.date(Lead.created_at) <= end,
        )
    ).all()
    campaign_keys = set(grouped)
    platform_rows: set[str] = set()
    for platform, campaign in attributed:
        if platform is None:
            continue
        if campaign:
            campaign_keys.add((platform, campaign))
        else:
            platform_rows.add(platform)

    result = [
        _row(session, platform, campaign, spend, start, end)
        for (platform, campaign), spend in sorted(grouped.items())
    ]
    for platform, campaign in sorted(campaign_keys - set(grouped)):
        result.append(_row(session, platform, campaign, Decimal("0.00"), start, end))
    for platform in sorted(platform_rows):
        result.append(_row(session, platform, None, Decimal("0.00"), start, end))
    return sorted(result, key=lambda item: (item.platform, item.campaign))
