"""Masked client showcase. Engine is supplied at request time for test isolation."""

from collections.abc import Callable
from datetime import date
from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session, selectinload

from app.contracts import serialize_inspection, serialize_period
from app.models import Client, Contract, Object, Transaction
from app.objects import serialize_contract, serialize_object


def summary(row: Client) -> dict[str, object]:
    today = date.today()
    contracts = [
        obj.contract for obj in row.objects if obj.status != "inactive" and obj.contract
    ]
    active = sum(
        (contract.start_date is None or contract.start_date <= today)
        and (contract.end_date is None or contract.end_date >= today)
        for contract in contracts
    )
    return {
        "id": row.id,
        "name": row.name,
        "client_type": row.client_type,
        "inn": row.inn_masked,
        "legal_address": row.legal_address_masked,
        "active_contracts": active,
    }


def clients_router(get_engine: Callable[[], Engine]) -> APIRouter:
    router = APIRouter(prefix="/api/clients", tags=["clients"])

    @router.get("")
    def list_clients(
        q: str = Query(default="", max_length=200),
        client_type: Literal["legal_entity", "sole_proprietor"] | None = None,
    ) -> list[dict[str, object]]:
        with Session(get_engine()) as session:
            statement = select(Client).where(
                Client.client_type.in_(["legal_entity", "sole_proprietor"])
            )
            if client_type:
                statement = statement.where(Client.client_type == client_type)
            rows = session.scalars(
                statement.options(
                    selectinload(Client.objects).selectinload(Object.contract)
                )
            ).all()
            needle = q.strip().casefold()
            return [
                summary(row)
                for row in sorted(rows, key=lambda row: (row.name.casefold(), row.id))
                if not needle
                or needle in row.name.casefold()
                or needle in (row.inn_masked or "")
            ]

    @router.get("/{client_id}")
    def client_card(client_id: int) -> dict[str, object]:
        with Session(get_engine()) as session:
            row = session.get(Client, client_id)
            if row is None or row.client_type not in (
                "legal_entity",
                "sole_proprietor",
            ):
                raise HTTPException(status_code=404, detail="Клиент не найден")
            objects = sorted(row.objects, key=lambda item: item.id)
            contracts: list[Contract] = [
                obj.contract for obj in objects if obj.contract
            ]
            object_ids = [obj.id for obj in objects]
            transactions = session.scalars(
                select(Transaction)
                .where(
                    (Transaction.client_id == row.id)
                    | (
                        Transaction.client_id.is_(None)
                        & Transaction.object_id.in_(object_ids)
                    )
                )
                .order_by(Transaction.operation_date.desc(), Transaction.id.desc())
            ).all()
            return {
                **summary(row),
                "requisites": {
                    "phone": row.phone,
                    "representative": row.representative,
                    "representative_role": row.representative_role,
                    "kpp": row.kpp_masked,
                    "registration_number": row.registration_number_masked,
                    "bank_details": row.bank_details_masked,
                },
                "objects": [
                    serialize_object(obj).model_dump(mode="json") for obj in objects
                ],
                "contracts": [serialize_contract(contract) for contract in contracts],
                "documents": [
                    serialize_period(period)
                    for contract in contracts
                    for period in contract.periods
                ],
                "transactions": [
                    {
                        "id": tx.id,
                        "operation_date": tx.operation_date,
                        "amount": f"{tx.amount:.2f}",
                        "kind": tx.kind,
                        "category": tx.category,
                        "client_id": tx.client_id,
                        "tags": tx.tags or [],
                    }
                    for tx in transactions
                ],
                "inspections": [
                    serialize_inspection(report)
                    for contract in contracts
                    for report in contract.inspection_reports
                ],
                "treatments": [
                    {
                        "id": treatment.id,
                        "object_id": obj.id,
                        "performed_at": treatment.performed_at,
                    }
                    for obj in objects
                    for treatment in obj.treatments
                ],
            }

    return router
