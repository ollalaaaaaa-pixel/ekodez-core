from collections.abc import Callable

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import Engine, event, inspect, select
from sqlalchemy.orm import Session

from app.finance_categories import INCOME_CATEGORIES_V1
from app.models import (
    BankCategoryMapping,
    ExpenseCategory,
    Object,
    Transaction,
    TransactionCategory,
)


def category_titles(session: Session, kind: str) -> list[str]:
    """Legacy fallback only for fixtures without seeded categories."""
    if session.scalar(select(TransactionCategory.id).limit(1)) is not None:
        return list(
            session.scalars(
                select(TransactionCategory.title)
                .where(
                    TransactionCategory.kind == kind,
                    TransactionCategory.is_active.is_(True),
                )
                .order_by(TransactionCategory.sort_order, TransactionCategory.id)
            )
        )
    if kind == "income":
        return list(INCOME_CATEGORIES_V1)
    return list(
        session.scalars(
            select(ExpenseCategory.name).where(ExpenseCategory.is_active.is_(True))
        )
    )


@event.listens_for(Session, "before_flush")
def sync_transaction_links(session, flush_context, instances):
    """Keep all entry points, including bank import and lead closure, consistent."""
    for row in list(session.new) + list(session.dirty):
        if not isinstance(row, Transaction):
            continue
        state = inspect(row)
        if row in session.new or state.attrs.object_id.history.has_changes():
            if row.object_id is not None:
                obj = session.get(Object, row.object_id)
                if obj:
                    row.client_id = obj.client_id
            elif row not in session.new:
                row.client_id = None
        if (
            row in session.new
            or state.attrs.category.history.has_changes()
            or state.attrs.kind.history.has_changes()
        ):
            mapping = (
                session.get(BankCategoryMapping, (row.kind, row.category))
                if row.category
                else None
            )
            category = (
                session.get(TransactionCategory, mapping.category_id)
                if mapping
                else session.scalar(
                    select(TransactionCategory).where(
                        TransactionCategory.kind == row.kind,
                        TransactionCategory.title == row.category,
                    )
                )
            )
            row.category_id = category.id if category else None


class CategoryIn(BaseModel):
    title: str = Field(min_length=1, max_length=100)
    kind: str
    sort_order: int = Field(default=0, ge=0)

    @field_validator("title")
    @classmethod
    def nonblank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Укажите название категории")
        return value.strip()


class ReorderIn(BaseModel):
    items: list["ReorderItem"]


class ReorderItem(BaseModel):
    model_config = {"extra": "forbid"}
    id: int = Field(gt=0)
    sort_order: int = Field(ge=0)


def categories_router(get_engine: Callable[[], Engine]) -> APIRouter:
    router = APIRouter(prefix="/api/transaction-categories", tags=["finance"])

    def validate_kind(kind: str) -> None:
        if kind not in {"income", "expense"}:
            raise HTTPException(422, "kind must be income or expense")

    @router.get("")
    def list_categories(kind: str | None = None):
        with Session(get_engine()) as session:
            statement = select(TransactionCategory).where(
                TransactionCategory.is_active.is_(True)
            )
            if kind is not None:
                validate_kind(kind)
                statement = statement.where(TransactionCategory.kind == kind)
            rows = session.scalars(
                statement.order_by(
                    TransactionCategory.sort_order,
                    TransactionCategory.id,
                )
            ).all()
            return [
                {
                    "id": row.id,
                    "title": row.title,
                    "kind": row.kind,
                    "sort_order": row.sort_order,
                    "is_active": row.is_active,
                }
                for row in rows
            ]

    @router.post("")
    def create_category(payload: CategoryIn):
        validate_kind(payload.kind)
        with Session(get_engine()) as session:
            if session.get(BankCategoryMapping, (payload.kind, payload.title)):
                raise HTTPException(409, "Название закреплено за банковским правилом")
            if session.scalar(
                select(TransactionCategory).where(
                    TransactionCategory.kind == payload.kind,
                    TransactionCategory.title == payload.title.strip(),
                )
            ):
                raise HTTPException(409, "category already exists")
            row = TransactionCategory(
                title=payload.title.strip(),
                kind=payload.kind,
                sort_order=payload.sort_order,
            )
            session.add(row)
            session.commit()
            session.refresh(row)
            return {
                "id": row.id,
                "title": row.title,
                "kind": row.kind,
                "sort_order": row.sort_order,
                "is_active": row.is_active,
            }

    @router.patch("/reorder")
    def reorder(payload: ReorderIn | list[ReorderItem]):
        items = payload.items if isinstance(payload, ReorderIn) else payload
        ids = [item.id for item in items]
        orders = [item.sort_order for item in items]
        if (
            any(value is None or value < 0 for value in orders)
            or len(ids) != len(set(ids))
            or len(orders) != len(set(orders))
        ):
            raise HTTPException(422, "unique non-negative sort_order and ids required")
        with Session(get_engine()) as session:
            rows = session.scalars(
                select(TransactionCategory).where(
                    TransactionCategory.id.in_(ids),
                    TransactionCategory.is_active.is_(True),
                )
            ).all()
            if len(rows) != len(ids):
                raise HTTPException(404, "category not found")
            by_id = {row.id: row for row in rows}
            for item in items:
                by_id[item.id].sort_order = item.sort_order
            session.commit()
            return {"updated": len(rows)}

    @router.patch("/{category_id}")
    def update_category(category_id: int, payload: CategoryIn):
        validate_kind(payload.kind)
        with Session(get_engine()) as session:
            row = session.get(TransactionCategory, category_id)
            if row is None or not row.is_active:
                raise HTTPException(404, "category not found")
            if payload.kind != row.kind:
                raise HTTPException(422, "Тип существующей категории менять нельзя")
            mapping = session.get(BankCategoryMapping, (row.kind, payload.title))
            if mapping and mapping.category_id != row.id:
                raise HTTPException(409, "Название закреплено за банковским правилом")
            duplicate = session.scalar(
                select(TransactionCategory).where(
                    TransactionCategory.kind == row.kind,
                    TransactionCategory.title == payload.title,
                    TransactionCategory.id != row.id,
                )
            )
            if duplicate:
                raise HTTPException(409, "Категория уже существует")
            row.title, row.kind, row.sort_order = (
                payload.title.strip(),
                payload.kind,
                payload.sort_order,
            )
            session.commit()
            return {
                "id": row.id,
                "title": row.title,
                "kind": row.kind,
                "sort_order": row.sort_order,
                "is_active": row.is_active,
            }

    @router.delete("/{category_id}")
    def delete_category(category_id: int):
        with Session(get_engine()) as session:
            row = session.get(TransactionCategory, category_id)
            if row is None or not row.is_active:
                raise HTTPException(404, "category not found")
            row.is_active = False
            session.commit()
            return {"id": row.id, "is_active": False}

    return router
