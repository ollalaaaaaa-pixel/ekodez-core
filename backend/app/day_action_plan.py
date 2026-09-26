"""Read-only, role-filtered overview of work due today."""

from datetime import date
from typing import Literal, cast

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.master_workflow import list_due_leads
from app.models import ContractPeriod, Lead, Object, Transaction
from app.reports.daily import list_due_objects, list_low_stock_inventory


def build_action_plan(
    session: Session,
    role: Literal["owner", "master"],
    today: date,
    *,
    include_all: bool = False,
) -> dict[str, object]:
    due_leads = list_due_leads(session, today)
    if role == "master":
        due_leads = [lead for lead in due_leads if lead.performed_by == "Алексей"]

    due_objects = list_due_objects(session, today)
    if role == "master":
        linked_ids = set(
            session.scalars(
                select(Lead.object_id).where(
                    Lead.performed_by == "Алексей",
                    Lead.status.in_(("new", "in_work")),
                    Lead.object_id.is_not(None),
                )
            ).all()
        )
        due_objects = [obj for obj in due_objects if obj.id in linked_ids]

    low_inventory = sorted(list_low_stock_inventory(session), key=lambda row: row.id)
    counts = {
        "lead_overdue": sum(
            lead.execution_date < today for lead in due_leads if lead.execution_date
        ),
        "lead_today": sum(lead.execution_date == today for lead in due_leads),
        "object_due": len(due_objects),
        "object_overdue": sum(
            obj.next_treatment_date < today
            for obj in due_objects
            if obj.next_treatment_date
        ),
        "object_today": sum(obj.next_treatment_date == today for obj in due_objects),
        "inventory_low": len(low_inventory),
    }

    shown_leads = due_leads if include_all else due_leads[:5]
    linked_object_dates = {
        (lead.object_id, lead.execution_date)
        for lead in shown_leads
        if lead.object_id is not None
    }
    due_object_ids = {obj.id for obj in due_objects}
    lead_items: list[dict[str, object]] = []
    for lead in shown_leads:
        lead_items.append(
            {
                "kind": "lead",
                "id": lead.id,
                "due_date": (
                    lead.execution_date.isoformat() if lead.execution_date else None
                ),
                "status": lead.status,
                "urgency": (
                    "overdue"
                    if lead.execution_date and lead.execution_date < today
                    else "today"
                ),
                "masked_label": f"Заявка #{lead.id}",
                "target": {"screen": "leads", "kind": "lead", "id": lead.id},
                "linked_object_due": lead.object_id in due_object_ids,
            }
        )
    object_items = [
        {
            "kind": "object",
            "id": obj.id,
            "due_date": (
                obj.next_treatment_date.isoformat() if obj.next_treatment_date else None
            ),
            "status": obj.status,
            "urgency": (
                "overdue"
                if obj.next_treatment_date and obj.next_treatment_date < today
                else "today"
            ),
            "masked_label": f"Объект #{obj.id}",
            "target": {"screen": "objects", "kind": "object", "id": obj.id},
        }
        for obj in due_objects
        if (obj.id, obj.next_treatment_date) not in linked_object_dates
    ]
    if not include_all:
        object_items = object_items[:5]
    inventory_items = [
        {
            "kind": "inventory",
            "id": row.id,
            "due_date": None,
            "status": "low_stock",
            "urgency": "attention",
            "masked_label": f"Препарат #{row.id}",
            "target": {"screen": "inventory", "kind": "inventory", "id": row.id},
        }
        for row in (low_inventory if include_all else low_inventory[:5])
    ]
    items = lead_items + object_items
    document_items: list[dict[str, object]] = []
    review_transactions: list[Transaction] = []
    if role == "owner":
        periods = list(
            session.scalars(
                select(ContractPeriod)
                .where(ContractPeriod.period_month <= today.replace(day=1))
                .order_by(ContractPeriod.period_month, ContractPeriod.id)
            ).all()
        )
        for period in periods:
            service_object = period.contract.object
            if service_object is None:
                continue
            statuses: list[str] = []
            if period.generated_at is not None and period.work_act_status == "draft":
                statuses.append("черновик акта")
            if period.paid_service_due and not period.invoice_number:
                statuses.append("проверить счёт")
            for status in statuses:
                document_items.append(
                    {
                        "kind": "document",
                        "id": period.id,
                        "period_id": period.id,
                        "due_date": period.period_month.isoformat(),
                        "status": status,
                        "urgency": "attention",
                        "masked_label": f"Документы объекта #{service_object.id}",
                        "target": {
                            "screen": "objects",
                            "kind": "document",
                            "id": service_object.id,
                            "periodId": period.id,
                            "periodMonth": period.period_month.strftime("%Y-%m"),
                        },
                    }
                )
        if today.day == 25:
            generated_contract_ids = {
                period.contract_id
                for period in periods
                if period.period_month == today.replace(day=1)
                and period.generated_at is not None
            }
            contract_objects = session.scalars(
                select(Object)
                .where(Object.contract_id.is_not(None), Object.status != "inactive")
                .order_by(Object.id)
            ).all()
            for obj in contract_objects:
                if obj.contract_id in generated_contract_ids:
                    continue
                document_items.append(
                    {
                        "kind": "document",
                        "id": obj.id,
                        "due_date": today.isoformat(),
                        "status": "акт к выпуску",
                        "urgency": "attention",
                        "masked_label": f"Документы объекта #{obj.id}",
                        "target": {
                            "screen": "objects",
                            "kind": "document",
                            "id": obj.id,
                            "periodMonth": today.strftime("%Y-%m"),
                        },
                    }
                )
        review_transactions = list(
            session.scalars(
                select(Transaction)
                .where(Transaction.review_required.is_(True))
                .order_by(Transaction.operation_date, Transaction.id)
            ).all()
        )
        transaction_items = [
            {
                "kind": "transaction",
                "id": row.id,
                "due_date": row.operation_date.isoformat(),
                "status": "на проверку",
                "urgency": "attention",
                "masked_label": f"Операция #{row.id}",
                "target": {"screen": "finance", "kind": "transaction", "id": row.id},
            }
            for row in (review_transactions if include_all else review_transactions[:5])
        ]
        counts["document_review"] = len(document_items)
        counts["transaction_review"] = len(review_transactions)
        items += (
            document_items if include_all else document_items[:5]
        ) + transaction_items
    items += inventory_items
    priority = {"overdue": 0, "today": 1, "attention": 2}
    items.sort(
        key=lambda item: (
            3 if item["kind"] == "inventory" else priority[str(item["urgency"])],
            str(item["due_date"] or today.isoformat()),
            cast(int, item["id"]),
            str(item["kind"]),
        )
    )
    result: dict[str, object] = {
        "date": today.isoformat(),
        "role": role,
        "counts": counts,
        "items": items,
    }
    if include_all:
        result["group_ids"] = {
            "lead": [lead.id for lead in due_leads],
            "object": [obj.id for obj in due_objects],
            "document": sorted(
                {
                    cast(int, cast(dict[str, object], item["target"])["id"])
                    for item in document_items
                }
            ),
            "transaction": [row.id for row in review_transactions],
            "inventory": [row.id for row in low_inventory],
        }
    return result
