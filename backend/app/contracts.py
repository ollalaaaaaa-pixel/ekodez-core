from datetime import date, datetime
from decimal import Decimal
from typing import Literal, Self

from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Client, Contract, ContractPeriod, InspectionReport
from app.objects import decimal_string

BillingClientType = Literal["legal_entity", "sole_proprietor", "individual"]
InspectionResult = Literal["not_required", "required"]
DocumentStatus = Literal["draft", "signed"]


class DocumentProfileIn(BaseModel):
    executor_bank_details: str = Field(min_length=1)
    executor_inn: str = Field(min_length=1, max_length=20)
    executor_ogrnip: str = Field(min_length=1, max_length=30)
    tax_mode: str = Field(min_length=1, max_length=200)


class BillingClientIn(BaseModel):
    client_type: BillingClientType
    name: str = Field(min_length=1, max_length=200)
    phone: str | None = Field(default=None, max_length=50)
    representative: str | None = Field(default=None, max_length=200)
    representative_role: str | None = Field(default=None, max_length=200)
    inn: str | None = Field(default=None, max_length=20)
    kpp: str | None = Field(default=None, max_length=20)
    registration_number: str | None = Field(default=None, max_length=30)
    legal_address: str | None = Field(default=None, max_length=500)
    bank_details: str | None = None

    @field_validator("name")
    @classmethod
    def strip_name(cls, value: str) -> str:
        return value.strip()


class BillingClientOut(BillingClientIn):
    id: int
    object_id: int


class InspectionReportIn(BaseModel):
    inspection_date: date | None = None
    control_date: date | None = None
    ksp_count: int | None = Field(default=None, ge=0)
    derat_glue_count: int | None = Field(default=None, ge=0)
    bait_count: int | None = Field(default=None, ge=0)
    rodents_caught: int | None = Field(default=None, ge=0)
    deratization_result: InspectionResult = "not_required"
    disinsection_glue_count: int | None = Field(default=None, ge=0)
    insects_caught: int | None = Field(default=None, ge=0)
    disinsection_result: InspectionResult = "not_required"
    status: DocumentStatus = "draft"
    signed_at: datetime | None = None

    @model_validator(mode="after")
    def signed_requires_timestamp(self) -> Self:
        if self.status == "signed" and self.signed_at is None:
            raise ValueError("signed inspection requires signed_at")
        return self


class InspectionReportOut(BaseModel):
    id: int
    contract_id: int
    report_month: date
    inspection_date: date | None
    control_date: date | None
    ksp_count: int
    derat_glue_count: int
    bait_count: int
    rodents_caught: int
    deratization_result: InspectionResult
    disinsection_glue_count: int
    insects_caught: int
    disinsection_result: InspectionResult
    status: DocumentStatus
    signed_at: datetime | None


class ContractPeriodIn(BaseModel):
    preparations: str | None = None
    infestation_degree: str | None = Field(default=None, min_length=1, max_length=100)
    extra_services: list[str] | None = None
    invoice_number: str | None = Field(default=None, min_length=1, max_length=100)
    invoice_date: date | None = None
    work_act_status: DocumentStatus | None = None
    work_act_signed_at: datetime | None = None
    transaction_id: int | None = None


class ContractPeriodOut(BaseModel):
    id: int
    contract_id: int
    period_month: date
    paid_service_due: bool
    price_snapshot: str | None
    preparations: str | None
    infestation_degree: str
    extra_services: list[str]
    invoice_number: str | None
    invoice_date: date | None
    work_act_status: DocumentStatus
    work_act_signed_at: datetime | None
    transaction_id: int | None
    generated_at: datetime | None
    file_manifest: list[dict[str, object]]


def month_start(value: date) -> date:
    return value.replace(day=1)


def parse_month(value: str) -> date:
    try:
        parsed = date.fromisoformat(f"{value}-01")
    except ValueError as error:
        raise ValueError("month must use YYYY-MM") from error
    return parsed


def is_paid_month(contract: Contract, value: date) -> bool:
    if contract.periodicity == "monthly":
        return True
    if contract.periodicity in {"semiannual", "custom"}:
        return value.month in set(contract.service_months or [])
    raise ValueError("contract periodicity is not configured")


def next_invoice_number(session: Session) -> str:
    numbers = session.scalars(
        select(ContractPeriod.invoice_number).where(
            ContractPeriod.invoice_number.is_not(None)
        )
    ).all()
    numeric = [int(value) for value in numbers if value is not None and value.isdigit()]
    return str(max(numeric, default=0) + 1)


def get_or_create_period(
    session: Session, contract: Contract, value: date
) -> ContractPeriod:
    period_month = month_start(value)
    existing = session.scalar(
        select(ContractPeriod).where(
            ContractPeriod.contract_id == contract.id,
            ContractPeriod.period_month == period_month,
        )
    )
    if existing is not None:
        return existing

    previous = session.scalar(
        select(ContractPeriod)
        .where(
            ContractPeriod.contract_id == contract.id,
            ContractPeriod.period_month < period_month,
        )
        .order_by(ContractPeriod.period_month.desc())
        .limit(1)
    )
    paid_service_due = is_paid_month(contract, period_month)
    row = ContractPeriod(
        contract=contract,
        period_month=period_month,
        paid_service_due=paid_service_due,
        price_snapshot=(Decimal(contract.price) if paid_service_due else None),
        preparations=previous.preparations if previous is not None else None,
        infestation_degree="начальная",
        extra_services=[],
        invoice_number=next_invoice_number(session) if paid_service_due else None,
        work_act_status="draft",
        file_manifest=[],
    )
    session.add(row)
    session.flush()
    return row


def serialize_billing_client(
    row: Client, values: dict[str, str | None] | None = None
) -> BillingClientOut:
    data = values or {
        "client_type": row.client_type,
        "name": row.name,
        "phone": row.phone,
        "representative": row.representative,
        "representative_role": row.representative_role,
        "inn": row.inn_masked,
        "kpp": row.kpp_masked,
        "registration_number": row.registration_number_masked,
        "legal_address": row.legal_address_masked,
        "bank_details": row.bank_details_masked,
    }
    return BillingClientOut(id=row.id, object_id=row.object_id, **data)  # type: ignore[arg-type]


def serialize_inspection(row: InspectionReport) -> InspectionReportOut:
    return InspectionReportOut(
        id=row.id,
        contract_id=row.contract_id,
        report_month=row.report_month,
        inspection_date=row.inspection_date,
        control_date=row.control_date,
        ksp_count=row.ksp_count,
        derat_glue_count=row.derat_glue_count,
        bait_count=row.bait_count,
        rodents_caught=row.rodents_caught,
        deratization_result=row.deratization_result,  # type: ignore[arg-type]
        disinsection_glue_count=row.disinsection_glue_count,
        insects_caught=row.insects_caught,
        disinsection_result=row.disinsection_result,  # type: ignore[arg-type]
        status=row.status,  # type: ignore[arg-type]
        signed_at=row.signed_at,
    )


def serialize_period(row: ContractPeriod) -> ContractPeriodOut:
    return ContractPeriodOut(
        id=row.id,
        contract_id=row.contract_id,
        period_month=row.period_month,
        paid_service_due=row.paid_service_due,
        price_snapshot=(
            decimal_string(row.price_snapshot)
            if row.price_snapshot is not None
            else None
        ),
        preparations=row.preparations,
        infestation_degree=row.infestation_degree,
        extra_services=row.extra_services or [],
        invoice_number=row.invoice_number,
        invoice_date=row.invoice_date,
        work_act_status=row.work_act_status,  # type: ignore[arg-type]
        work_act_signed_at=row.work_act_signed_at,
        transaction_id=row.transaction_id,
        generated_at=row.generated_at,
        file_manifest=row.file_manifest or [],
    )
