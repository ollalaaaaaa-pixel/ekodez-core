from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Literal, Self

from pydantic import BaseModel, Field, field_validator, model_validator

from app.models import Contract, Object, Treatment
from app.security.pii import (
    decrypt_pii,
    encrypt_pii,
    mask_address,
    mask_name,
    mask_phone,
)

ObjectType = Literal[
    "restaurant", "gym", "kindergarten", "apartment", "office", "other"
]
StoredObjectStatus = Literal["active", "warranty", "inactive"]
ObjectStatus = Literal["active", "warranty", "overdue", "inactive"]

MONEY_QUANTUM = Decimal("0.01")


class PiiEncryptionUnavailable(ValueError):
    pass


class ContractIn(BaseModel):
    number: str = Field(min_length=1, max_length=100)
    price: Decimal = Field(gt=0)
    contract_date: date | None = None
    periodicity: Literal["monthly", "semiannual", "custom"]
    service_months: list[int] = Field(default_factory=list)
    payment_term_business_days: int = Field(default=5, gt=0)
    default_ksp: int = Field(default=5, ge=0)
    default_derat_glue: int = Field(default=5, ge=0)
    default_baits: int = Field(default=5, ge=0)
    default_disinsection_glue: int = Field(default=6, ge=0)
    start_date: date | None = None
    end_date: date | None = None

    @field_validator("number")
    @classmethod
    def validate_number(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("contract number is required")
        return stripped

    @model_validator(mode="after")
    def validate_service_months(self) -> Self:
        normalized = sorted(set(self.service_months))
        if any(month < 1 or month > 12 for month in normalized):
            raise ValueError("service months must be between 1 and 12")
        if self.periodicity == "monthly" and normalized:
            raise ValueError("monthly contracts do not use service months")
        if self.periodicity == "semiannual" and len(normalized) != 2:
            raise ValueError("semiannual contracts require exactly two months")
        if self.periodicity == "custom" and not normalized:
            raise ValueError("custom contracts require service months")
        self.service_months = normalized
        return self


class ContractOut(BaseModel):
    id: int
    number: str
    price: str
    contract_date: date | None
    periodicity: Literal["monthly", "semiannual", "custom"] | None
    service_months: list[int]
    payment_term_business_days: int
    default_ksp: int
    default_derat_glue: int
    default_baits: int
    default_disinsection_glue: int
    start_date: date | None
    end_date: date | None


class ObjectIn(BaseModel):
    name: str = Field(min_length=1, max_length=300)
    address: str = Field(min_length=1, max_length=500)
    type: ObjectType
    area_sqm: Decimal = Field(gt=0)
    contract: ContractIn | None = None
    risk_points: list[str] = Field(default_factory=list)
    last_treatment_date: date | None = None
    next_treatment_date: date | None = None
    status: StoredObjectStatus = "active"

    @field_validator("name", "address")
    @classmethod
    def validate_text(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("value is required")
        return stripped


class ObjectUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=300)
    address: str | None = Field(default=None, min_length=1, max_length=500)
    type: ObjectType | None = None
    area_sqm: Decimal | None = Field(default=None, gt=0)
    contract: ContractIn | None = None
    risk_points: list[str] | None = None
    last_treatment_date: date | None = None
    next_treatment_date: date | None = None
    status: StoredObjectStatus | None = None

    @field_validator("name", "address")
    @classmethod
    def validate_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        if not stripped:
            raise ValueError("value is required")
        return stripped

    @model_validator(mode="after")
    def reject_null_required_fields(self) -> Self:
        required = {"name", "address", "type", "area_sqm", "risk_points", "status"}
        for field in required & self.model_fields_set:
            if getattr(self, field) is None:
                raise ValueError(f"{field} cannot be null")
        return self


class ObjectOut(BaseModel):
    id: int
    name: str
    address: str
    type: ObjectType
    area_sqm: str
    contract: ContractOut | None
    risk_points: list[str]
    last_treatment_date: date | None
    next_treatment_date: date | None
    status: ObjectStatus


class TreatmentOut(BaseModel):
    id: int
    lead_id: int | None
    object_id: int
    chemicals_used: list[dict[str, object]]
    performed_at: datetime
    performed_by: str
    notes: str | None


def decimal_string(value: Decimal) -> str:
    return str(value.quantize(MONEY_QUANTUM, rounding=ROUND_HALF_UP))


def effective_status(row: Object, today: date | None = None) -> ObjectStatus:
    current_date = today or date.today()
    if row.next_treatment_date is not None and row.next_treatment_date < current_date:
        return "overdue"
    return row.status  # type: ignore[return-value]


def protect_address(object_type: ObjectType, address: str) -> tuple[str, str | None]:
    if object_type != "apartment":
        return address, None
    encrypted = encrypt_pii({"address": address})
    if encrypted is None:
        raise PiiEncryptionUnavailable("PII encryption is unavailable")
    return mask_address(address), encrypted


def protect_client_pii(name: str, phone: str | None) -> dict[str, str | None]:
    encrypted = encrypt_pii({"client_name": name, "phone": phone})
    if encrypted is None:
        raise PiiEncryptionUnavailable("PII encryption is unavailable")
    return {
        "name": mask_name(name),
        "phone": mask_phone(phone) or None,
        "encrypted_pii": encrypted,
    }


def reveal_address(row: Object) -> str:
    if row.type != "apartment":
        return row.address
    payload = decrypt_pii(row.encrypted_address)
    return payload.get("address") or row.address


def serialize_contract(row: Contract | None) -> ContractOut | None:
    if row is None:
        return None
    return ContractOut(
        id=row.id,
        number=row.number,
        price=decimal_string(row.price),
        contract_date=row.contract_date,
        periodicity=row.periodicity,  # type: ignore[arg-type]
        service_months=row.service_months or [],
        payment_term_business_days=row.payment_term_business_days,
        default_ksp=row.default_ksp,
        default_derat_glue=row.default_derat_glue,
        default_baits=row.default_baits,
        default_disinsection_glue=row.default_disinsection_glue,
        start_date=row.start_date,
        end_date=row.end_date,
    )


def serialize_object(row: Object, *, address: str | None = None) -> ObjectOut:
    return ObjectOut(
        id=row.id,
        name=row.name,
        address=row.address if address is None else address,
        type=row.type,  # type: ignore[arg-type]
        area_sqm=decimal_string(row.area_sqm),
        contract=serialize_contract(row.contract),
        risk_points=row.risk_points or [],
        last_treatment_date=row.last_treatment_date,
        next_treatment_date=row.next_treatment_date,
        status=effective_status(row),
    )


def serialize_treatment(row: Treatment) -> TreatmentOut:
    return TreatmentOut(
        id=row.id,
        lead_id=row.lead_id,
        object_id=row.object_id,
        chemicals_used=row.chemicals_used or [],
        performed_at=row.performed_at,
        performed_by=row.performed_by,
        notes=row.notes,
    )
