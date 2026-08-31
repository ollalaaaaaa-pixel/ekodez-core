from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Self

from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import update
from sqlalchemy.orm import Session

from app.models import ChemicalUsage, Inventory, Lead, Object, Treatment

QUANTITY_QUANTUM = Decimal("0.001")
LOW_STOCK_RATIO = Decimal("0.10")


class InventoryNotFound(ValueError):
    pass


class InsufficientInventory(ValueError):
    pass


class RelatedRecordExists(ValueError):
    pass


class InventoryIn(BaseModel):
    chemical_name: str = Field(min_length=1, max_length=200)
    quantity: Decimal = Field(gt=0)
    unit: str = Field(min_length=1, max_length=30)
    batch_number: str = Field(min_length=1, max_length=100)
    expiry_date: date
    supplier: str = Field(min_length=1, max_length=200)

    @field_validator("chemical_name", "unit", "batch_number", "supplier")
    @classmethod
    def strip_text(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("value is required")
        return stripped


class InventoryUpdate(BaseModel):
    chemical_name: str | None = Field(default=None, min_length=1, max_length=200)
    quantity: Decimal | None = Field(default=None, ge=0)
    unit: str | None = Field(default=None, min_length=1, max_length=30)
    batch_number: str | None = Field(default=None, min_length=1, max_length=100)
    expiry_date: date | None = None
    supplier: str | None = Field(default=None, min_length=1, max_length=200)

    @field_validator("chemical_name", "unit", "batch_number", "supplier")
    @classmethod
    def strip_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        if not stripped:
            raise ValueError("value is required")
        return stripped

    @model_validator(mode="after")
    def reject_explicit_nulls(self) -> Self:
        for field in self.model_fields_set:
            if getattr(self, field) is None:
                raise ValueError(f"{field} cannot be null")
        return self


class InventoryOut(BaseModel):
    id: int
    chemical_name: str
    quantity: str
    initial_quantity: str
    unit: str
    batch_number: str
    expiry_date: date
    supplier: str
    low_stock: bool


class ChemicalUsageIn(BaseModel):
    inventory_id: int = Field(gt=0)
    quantity_used: Decimal = Field(gt=0)


class TreatmentIn(BaseModel):
    lead_id: int | None = None
    object_id: int = Field(gt=0)
    chemicals_used: list[ChemicalUsageIn] = Field(min_length=1)
    performed_at: datetime
    performed_by: str = Field(min_length=1, max_length=200)
    notes: str | None = None

    @field_validator("performed_by")
    @classmethod
    def strip_performer(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("performed_by is required")
        return stripped

    @model_validator(mode="after")
    def reject_duplicate_inventory(self) -> Self:
        inventory_ids = [row.inventory_id for row in self.chemicals_used]
        if len(inventory_ids) != len(set(inventory_ids)):
            raise ValueError("inventory_id must be unique within treatment")
        return self


class ChemicalUsageOut(BaseModel):
    id: int
    inventory_id: int
    chemical_name: str
    quantity_used: str
    unit: str


class InventoryTreatmentOut(BaseModel):
    id: int
    lead_id: int | None
    object_id: int
    chemicals_used: list[ChemicalUsageOut]
    performed_at: datetime
    performed_by: str
    notes: str | None


def quantity_string(value: Decimal) -> str:
    return str(value.quantize(QUANTITY_QUANTUM, rounding=ROUND_HALF_UP))


def is_low_stock(row: Inventory) -> bool:
    return row.quantity < row.initial_quantity * LOW_STOCK_RATIO


def serialize_inventory(row: Inventory) -> InventoryOut:
    return InventoryOut(
        id=row.id,
        chemical_name=row.chemical_name,
        quantity=quantity_string(row.quantity),
        initial_quantity=quantity_string(row.initial_quantity),
        unit=row.unit,
        batch_number=row.batch_number,
        expiry_date=row.expiry_date,
        supplier=row.supplier,
        low_stock=is_low_stock(row),
    )


def serialize_inventory_treatment(row: Treatment) -> InventoryTreatmentOut:
    usages = sorted(row.chemical_usages, key=lambda usage: usage.id)
    return InventoryTreatmentOut(
        id=row.id,
        lead_id=row.lead_id,
        object_id=row.object_id,
        chemicals_used=[
            ChemicalUsageOut(
                id=usage.id,
                inventory_id=usage.inventory_id,
                chemical_name=usage.inventory.chemical_name,
                quantity_used=quantity_string(usage.quantity),
                unit=usage.inventory.unit,
            )
            for usage in usages
        ],
        performed_at=row.performed_at,
        performed_by=row.performed_by,
        notes=row.notes,
    )


def apply_treatment_with_inventory(
    session: Session,
    *,
    lead_id: int | None,
    object_id: int,
    chemicals_used: list[ChemicalUsageIn],
    performed_at: datetime,
    performed_by: str,
    notes: str | None,
    allow_empty: bool = False,
) -> Treatment:
    if not chemicals_used and not allow_empty:
        raise ValueError("at least one inventory usage is required")
    inventory_ids = [row.inventory_id for row in chemicals_used]
    if len(inventory_ids) != len(set(inventory_ids)):
        raise ValueError("inventory_id must be unique within treatment")

    service_object = session.get(Object, object_id)
    if service_object is None:
        raise InventoryNotFound("object not found")
    if lead_id is not None and session.get(Lead, lead_id) is None:
        raise InventoryNotFound("lead not found")

    treatment = Treatment(
        lead_id=lead_id,
        object_id=object_id,
        chemicals_used=[],
        performed_at=performed_at,
        performed_by=performed_by,
        notes=notes,
    )
    session.add(treatment)
    session.flush()

    audit_rows: list[dict[str, object]] = []
    for requested in chemicals_used:
        inventory = session.get(Inventory, requested.inventory_id)
        if inventory is None:
            raise InventoryNotFound("inventory not found")
        result = session.execute(
            update(Inventory)
            .where(
                Inventory.id == requested.inventory_id,
                Inventory.quantity >= requested.quantity_used,
            )
            .values(quantity=Inventory.quantity - requested.quantity_used)
        )
        if getattr(result, "rowcount", 0) != 1:
            raise InsufficientInventory("insufficient inventory")
        usage = ChemicalUsage(
            inventory=inventory,
            treatment=treatment,
            quantity=requested.quantity_used,
        )
        session.add(usage)
        audit_rows.append(
            {
                "inventory_id": inventory.id,
                "chemical_name": inventory.chemical_name,
                "quantity_used": quantity_string(requested.quantity_used),
                "unit": inventory.unit,
            }
        )

    treatment.chemicals_used = audit_rows
    service_object.last_treatment_date = performed_at.date()
    session.flush()
    return treatment


def create_treatment_with_inventory(
    session: Session, payload: TreatmentIn
) -> Treatment:
    treatment = apply_treatment_with_inventory(
        session,
        lead_id=payload.lead_id,
        object_id=payload.object_id,
        chemicals_used=payload.chemicals_used,
        performed_at=payload.performed_at,
        performed_by=payload.performed_by,
        notes=payload.notes,
    )
    session.commit()
    session.refresh(treatment)
    return treatment
