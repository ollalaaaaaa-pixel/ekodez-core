from dataclasses import dataclass
from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.finance_categories import INCOME_CATEGORIES_V1, default_finance_category
from app.inventory import (
    ChemicalUsageIn,
    InsufficientInventory,
    InventoryNotFound,
    apply_treatment_with_inventory,
)
from app.models import Lead, Transaction, Treatment

MOSCOW = ZoneInfo("Europe/Moscow")
PERFORMERS = ("Артём", "Алексей")


class MasterWorkflowError(ValueError):
    pass


class InvalidExecutionDate(MasterWorkflowError):
    pass


class InvalidCompletion(MasterWorkflowError):
    pass


@dataclass(frozen=True)
class CompletionResult:
    lead_id: int
    treatment_id: int | None
    transaction_id: int | None
    already_done: bool


def moscow_today(now: datetime | None = None) -> date:
    current = now or datetime.now(UTC)
    if current.tzinfo is None:
        current = current.replace(tzinfo=UTC)
    return current.astimezone(MOSCOW).date()


def list_due_leads(session: Session, today: date) -> list[Lead]:
    return list(
        session.scalars(
            select(Lead)
            .where(
                Lead.status.in_(("new", "in_work")),
                Lead.execution_date.is_not(None),
                Lead.execution_date <= today,
            )
            .order_by(Lead.execution_date, Lead.id)
        ).all()
    )


def reschedule_lead(
    session: Session, lead_id: int, new_date: date, today: date
) -> Lead:
    if new_date < today:
        raise InvalidExecutionDate("execution date cannot be in the past")
    lead = session.get(Lead, lead_id)
    if lead is None:
        raise InvalidExecutionDate("lead not found")
    if lead.status not in ("new", "in_work"):
        raise InvalidExecutionDate("lead is not active")
    lead.execution_date = new_date
    session.commit()
    session.refresh(lead)
    return lead


def _existing_completion(session: Session, lead: Lead) -> CompletionResult:
    treatment_id = session.scalar(
        select(Treatment.id).where(Treatment.lead_id == lead.id).limit(1)
    )
    transaction_id = session.scalar(
        select(Transaction.id).where(Transaction.lead_id == lead.id).limit(1)
    )
    return CompletionResult(
        lead_id=lead.id,
        treatment_id=treatment_id,
        transaction_id=transaction_id,
        already_done=True,
    )


def complete_lead(
    session: Session,
    *,
    lead_id: int,
    category: str,
    performed_by: str,
    usages: list[ChemicalUsageIn],
    without_materials: bool,
    completed_at: datetime,
) -> CompletionResult:
    lead = session.get(Lead, lead_id)
    if lead is None:
        raise InvalidCompletion("lead not found")
    if lead.status == "done":
        return _existing_completion(session, lead)
    if lead.status not in ("new", "in_work"):
        raise InvalidCompletion("lead is not active")
    if lead.object_id is None:
        raise InvalidCompletion("lead object is required")
    if lead.execution_date is None:
        raise InvalidCompletion("execution date is required")
    if category not in INCOME_CATEGORIES_V1:
        raise InvalidCompletion("bad category")
    if performed_by not in PERFORMERS:
        raise InvalidCompletion("bad performer")
    if not usages and not without_materials:
        raise InvalidCompletion("materials choice is required")
    if usages and without_materials:
        raise InvalidCompletion("without_materials conflicts with usages")

    try:
        treatment = apply_treatment_with_inventory(
            session,
            lead_id=lead.id,
            object_id=lead.object_id,
            chemicals_used=usages,
            performed_at=completed_at,
            performed_by=performed_by,
            notes=f"Заявка #{lead.id}",
            allow_empty=without_materials,
        )
        lead.category = category
        lead.performed_by = performed_by
        lead.status = "done"
        normalized_completed_at = completed_at
        if normalized_completed_at.tzinfo is None:
            normalized_completed_at = normalized_completed_at.replace(tzinfo=UTC)
        lead.closed_at = normalized_completed_at.astimezone(UTC)

        transaction = session.scalar(
            select(Transaction).where(Transaction.lead_id == lead.id)
        )
        if lead.amount > 0 and transaction is None:
            transaction = Transaction(
                source="lead_auto",
                operation_date=lead.execution_date,
                amount=lead.amount,
                currency="RUB",
                counterparty=None,
                description=f"Автодоход по заявке #{lead.id}",
                category=lead.category or default_finance_category("income"),
                channel=None,
                entered_by=lead.performed_by,
                kind="income",
                review_required=False,
                needs_review=False,
                object_id=lead.object_id,
                lead_id=lead.id,
            )
            session.add(transaction)

        session.commit()
        session.refresh(treatment)
        if transaction is not None:
            session.refresh(transaction)
        return CompletionResult(
            lead_id=lead.id,
            treatment_id=treatment.id,
            transaction_id=transaction.id if transaction is not None else None,
            already_done=False,
        )
    except (InsufficientInventory, InventoryNotFound, ValueError):
        session.rollback()
        raise
