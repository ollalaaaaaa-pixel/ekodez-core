"""Calendar-window marketing metrics; no guessed profit or click-to-lead conversion."""

from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import TypedDict

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.lead_dictionaries import LEAD_SOURCE_LABELS
from app.models import Lead, Transaction

MARKETING_CHANNELS = {
    "yandex_direct": "Яндекс",
    "vk": "ВК",
    "avito": "Авито",
    "seo": "Прочее",
}


class MarketingRow(TypedDict):
    source: str
    label: str
    leads: int
    expenses: str
    paid_revenue: str
    cpl: str | None
    roas: str | None


class MarketingResult(TypedDict):
    channels: list[MarketingRow]
    unassigned_ad_expenses: str


def marketing_metrics(session: Session, start: date, end: date) -> MarketingResult:
    start_utc = datetime.combine(start, time.min) - timedelta(hours=3)
    end_utc = datetime.combine(end + timedelta(days=1), time.min) - timedelta(hours=3)
    leads = list(
        session.scalars(
            select(Lead).where(Lead.created_at >= start_utc, Lead.created_at < end_utc)
        )
    )
    transactions = list(
        session.scalars(
            select(Transaction).where(
                Transaction.operation_date >= start,
                Transaction.operation_date <= end,
            )
        )
    )
    # Payment attribution uses all linked leads, not only leads created in this window.
    linked_ids = {
        t.lead_id for t in transactions if t.kind == "income" and t.lead_id is not None
    }
    linked_sources = {
        lead_id: source
        for lead_id, source in session.execute(
            select(Lead.id, Lead.source).where(Lead.id.in_(linked_ids))
        ).all()
    }
    rows: list[MarketingRow] = []
    for source in MARKETING_CHANNELS:
        count = sum(lead.source == source for lead in leads)
        spend = sum(
            (
                t.amount
                for t in transactions
                if t.kind == "expense"
                and t.category == "Реклама"
                and t.marketing_source == source
            ),
            Decimal("0.00"),
        )
        revenue = sum(
            (
                t.amount
                for t in transactions
                if t.kind == "income"
                and t.lead_id is not None
                and linked_sources.get(t.lead_id) == source
            ),
            Decimal("0.00"),
        )
        rows.append(
            {
                "source": source,
                "label": LEAD_SOURCE_LABELS[source],
                "leads": count,
                "expenses": f"{spend:.2f}",
                "paid_revenue": f"{revenue:.2f}",
                "cpl": f"{spend / count:.2f}" if count else None,
                "roas": f"{revenue / spend:.2f}" if spend else None,
            }
        )
    unassigned = sum(
        (
            t.amount
            for t in transactions
            if t.kind == "expense"
            and t.category == "Реклама"
            and t.marketing_source not in MARKETING_CHANNELS
        ),
        Decimal("0.00"),
    )
    return {"channels": rows, "unassigned_ad_expenses": f"{unassigned:.2f}"}
