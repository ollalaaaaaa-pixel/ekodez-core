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

    def json(self) -> dict[str, object]:
        data = asdict(self)
        for key in ("spend", "revenue", "cpl", "romi"):
            value = data[key]
            data[key] = None if value is None else f"{value:.2f}"
        return data


def ads_metrics(session: Session, start: date, end: date) -> list[MetricRow]:
    spends = session.scalars(
        select(AdSpend).where(AdSpend.period_start <= end, AdSpend.period_end >= start)
    ).all()
    grouped: dict[tuple[str, str], Decimal] = {}
    for spend_row in spends:
        key = (spend_row.platform, spend_row.campaign)
        grouped[key] = grouped.get(key, Decimal("0.00")) + Decimal(spend_row.spend)
    campaign_counts: dict[str, int] = {}
    for platform, _ in grouped:
        campaign_counts[platform] = campaign_counts.get(platform, 0) + 1
    result: list[MetricRow] = []
    for (platform, campaign), spend in sorted(grouped.items()):
        lead_query = select(Lead.id).where(
            Lead.attributed_platform == platform,
            func.date(Lead.created_at) >= start,
            func.date(Lead.created_at) <= end,
        )
        if campaign_counts[platform] > 1:
            lead_query = lead_query.where(Lead.utm_campaign == campaign)
        lead_ids = session.scalars(lead_query).all()
        revenue = Decimal("0.00")
        if lead_ids:
            revenue = Decimal(
                session.scalar(
                    select(func.coalesce(func.sum(Transaction.amount), 0)).where(
                        Transaction.lead_id.in_(lead_ids), Transaction.kind == "income"
                    )
                )
                or 0
            )
        leads = len(lead_ids)
        cpl = (spend / leads).quantize(Decimal("0.01")) if leads else None
        romi = (
            ((revenue - spend) / spend * 100).quantize(Decimal("0.01"))
            if spend
            else None
        )
        result.append(
            MetricRow(
                platform,
                campaign,
                spend,
                leads,
                revenue,
                cpl,
                romi,
            )
        )
    return result
