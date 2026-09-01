import json
import os
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import TypedDict
from uuid import uuid4
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
from fastapi import FastAPI, File, HTTPException, Query, Request, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, field_serializer
from sqlalchemy import func, or_, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.bank_import import (
    MONEY_QUANTUM,
    BankImportError,
    BankRow,
    ClassificationResult,
    mask_inn,
    parse_amount,
    parse_tbank_xlsx,
    source_hash,
    transaction_comment,
)
from app.bank_import import (
    classify_transaction as classify_bank_transaction,
)
from app.business_calendar import CalendarRangeError, add_business_days
from app.channels import CHANNELS
from app.contracts import (
    BillingClientIn,
    BillingClientOut,
    ContractPeriodIn,
    ContractPeriodOut,
    DocumentProfileIn,
    InspectionReportIn,
    InspectionReportOut,
    get_or_create_period,
    parse_month,
    serialize_billing_client,
    serialize_inspection,
    serialize_period,
)
from app.db import create_app_engine
from app.document_packages import (
    DocumentTemplateError,
    build_month_package,
    resolve_package_file,
)
from app.finance_categories import (
    INCOME_CATEGORIES_V1,
    classify_finance,
    default_finance_category,
)
from app.inventory import (
    LOW_STOCK_RATIO,
    InsufficientInventory,
    InventoryIn,
    InventoryNotFound,
    InventoryOut,
    InventoryTreatmentOut,
    InventoryUpdate,
    TreatmentIn,
    create_treatment_with_inventory,
    serialize_inventory,
    serialize_inventory_treatment,
)
from app.lead_dictionaries import LEAD_SOURCES
from app.lead_parser import parse_amount_note, parse_order_text
from app.master_workflow import PERFORMERS
from app.models import (
    ChemicalUsage,
    Client,
    Contract,
    ContractPeriod,
    ExpenseCategory,
    InspectionReport,
    Inventory,
    Lead,
    Object,
    Transaction,
    Treatment,
)
from app.objects import (
    ContractIn,
    ObjectIn,
    ObjectOut,
    ObjectStatus,
    ObjectType,
    ObjectUpdate,
    PiiEncryptionUnavailable,
    TreatmentOut,
    effective_status,
    protect_address,
    reveal_address,
    serialize_object,
    serialize_treatment,
)
from app.reports.daily import (
    ManualReportCooldown,
    ReportsConfigurationError,
    TelegramDeliveryError,
    send_daily_report,
)
from app.reports.scheduler import reports_status, start_report_scheduler
from app.security.pii import (
    decrypt_pii,
    decrypt_sensitive_mapping,
    encrypt_sensitive_mapping,
    mask_address,
    mask_name,
    mask_phone,
    pii_status,
    protect_lead_pii,
)
from app.tg_poller import poller_started, start_poller

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "")

DOCUMENT_OUTPUT_ROOT = Path(r"C:\D\Экодез\hostels-docs")
DOCUMENT_PROFILE_PATH = DOCUMENT_OUTPUT_ROOT / "company-profile.json"
DOCUMENT_TEMPLATE_DIR = Path(__file__).parents[2] / "docs" / "templates"

engine = create_app_engine(DATABASE_URL)

app = FastAPI(title="Ekodez Core")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def _start_telegram_poller() -> None:
    start_poller(engine)
    start_report_scheduler(engine)


class TransactionIn(BaseModel):
    source: str = "manual"
    operation_date: date
    amount: Decimal
    currency: str = "RUB"
    counterparty: str | None = None
    description: str | None = None
    channel: str | None = None
    kind: str = "unknown"
    review_required: bool = True
    object_id: int | None = None


class TransactionOut(BaseModel):
    model_config = {"from_attributes": True}

    id: int
    source: str
    operation_date: date
    amount: Decimal
    currency: str
    counterparty: str | None
    description: str | None
    category: str | None
    channel: str | None
    kind: str
    review_required: bool
    object_id: int | None
    lead_id: int | None
    object_name: str | None


class FinanceSummary(BaseModel):
    income: Decimal
    expense: Decimal
    review_count: int


class ClassifyIn(BaseModel):
    kind: str
    review_required: bool = False
    amount: Decimal | None = None


class TransactionObjectIn(BaseModel):
    object_id: int | None


class DayEntryIn(BaseModel):
    model_config = {"populate_by_name": True}

    kind: str
    category: str
    channel: str | None = None
    amount: Decimal
    comment: str | None = None
    entered_by: str = "Артем"
    entry_date: date | None = Field(default=None, alias="date")
    object_id: int | None = None


class DashboardBestDay(BaseModel):
    date: date
    revenue: str


class DashboardObject(BaseModel):
    object_id: int
    name: str
    revenue: str


class DashboardService(BaseModel):
    category: str
    revenue: str


class DashboardDaily(BaseModel):
    date: date
    revenue: str
    expenses: str
    profit: str


class DashboardOut(BaseModel):
    revenue: str
    expenses: str
    profit: str
    margin_pct: str
    total_leads: int
    closed_leads: int
    conversion_rate: str
    average_check: str
    best_day: DashboardBestDay | None
    top_objects: list[DashboardObject]
    top_services: list[DashboardService]
    unassigned_revenue: str
    daily: list[DashboardDaily]


class ExpenseCategoryIn(BaseModel):
    name: str


class ExpenseCategoryOut(BaseModel):
    model_config = {"from_attributes": True}

    id: int
    name: str


class ChannelAnalyticsItem(BaseModel):
    channel: str
    total_amount: Decimal
    count: int
    avg_check: Decimal
    share_percent: Decimal


class ChannelAnalyticsOut(BaseModel):
    period_total: Decimal
    channels: list[ChannelAnalyticsItem]


class ChannelAnalyticsRow(TypedDict):
    channel: str
    total_amount: Decimal
    count: int
    avg_check: Decimal
    share_percent: Decimal


class BankPreviewOut(BaseModel):
    operation_type: str
    operation_date: date
    doc_number: str
    amount: Decimal
    description: str
    payment_purpose: str
    counterparty_name: str
    counterparty_inn: str
    counterparty_inn_masked: str
    source_hash: str
    kind: str
    category: str | None
    channel: str | None
    comment: str
    needs_review: bool
    is_transfer: bool


class BankConfirmRowIn(BaseModel):
    operation_type: str
    operation_date: date
    doc_number: str
    amount: Decimal
    description: str
    payment_purpose: str
    counterparty_name: str
    counterparty_inn: str
    source_hash: str = Field(min_length=64, max_length=64)
    category_override: str | None = None
    review_confirmed: bool = False


class BankConfirmIn(BaseModel):
    source_filename: str
    transactions: list[BankConfirmRowIn]


class BankConfirmOut(BaseModel):
    imported: int
    skipped_duplicates: int
    batch_id: str
    imported_income_amount: str
    imported_expense_amount: str
    duplicate_income_amount: str
    duplicate_expense_amount: str
    excluded_credit_amount: str
    excluded_debit_amount: str
    statement_credit_total: str
    statement_debit_total: str
    credit_reconciled: bool
    debit_reconciled: bool


class LeadOut(BaseModel):
    model_config = {"from_attributes": True}

    id: int
    source: str
    category: str | None
    external_id: str | None
    order_at: datetime | None
    client_name: str | None
    phone: str | None
    address: str | None
    area: str | None
    reason: str | None
    comment: str | None
    amount_note: str | None
    contract: str | None
    partner: str | None
    status: str
    amount: Decimal
    execution_date: date | None
    object_id: int | None
    performed_by: str

    @field_serializer("amount")
    def serialize_amount(self, value: Decimal) -> str:
        return f"{value:.2f}"


class RawTextIn(BaseModel):
    text: str
    source: str = "telegram"
    category: str | None = None
    amount: Decimal | None = Field(default=None, ge=0, decimal_places=2)
    execution_date: date | None = None


class LeadPatchIn(BaseModel):
    amount: Decimal | None = Field(default=None, ge=0, decimal_places=2)
    execution_date: date | None = None
    category: str | None = None
    object_id: int | None = Field(default=None, gt=0)
    performed_by: str | None = None


class LeadStatusIn(BaseModel):
    status: str


class DailyReportSendOut(BaseModel):
    status: str
    report_date: date
    sent_at: datetime
    recipient_key: str


@app.get("/health")
def health():
    return {
        "status": "ok",
        "telegram": "started" if poller_started() else "stopped",
        "pii": pii_status(),
        "reports": reports_status(),
    }


@app.get("/health/db")
def health_db():
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    return {"status": "ok", "database": "connected"}


@app.post("/api/reports/daily/send", response_model=DailyReportSendOut)
def send_daily_report_manually(request: Request):
    client_host = request.client.host if request.client else ""
    if client_host not in ("127.0.0.1", "::1"):
        raise HTTPException(
            status_code=403, detail="daily report send is localhost only"
        )
    try:
        result = send_daily_report(
            engine, "manual", datetime.now(ZoneInfo("Europe/Moscow"))
        )
    except ManualReportCooldown as error:
        raise HTTPException(
            status_code=429,
            detail="manual daily report is on cooldown",
            headers={"Retry-After": str(error.retry_after_seconds)},
        ) from error
    except ReportsConfigurationError as error:
        raise HTTPException(
            status_code=503, detail="daily reports are not configured"
        ) from error
    except TelegramDeliveryError as error:
        raise HTTPException(
            status_code=502, detail="Telegram delivery failed"
        ) from error
    return DailyReportSendOut(
        status=result.status,
        report_date=result.report_date,
        sent_at=result.sent_at,
        recipient_key=result.recipient_key,
    )


def _contract_from_input(payload: ContractIn) -> Contract:
    return Contract(
        number=payload.number.strip(),
        price=payload.price,
        contract_date=payload.contract_date,
        periodicity=payload.periodicity,
        service_months=payload.service_months,
        payment_term_business_days=payload.payment_term_business_days,
        default_ksp=payload.default_ksp,
        default_derat_glue=payload.default_derat_glue,
        default_baits=payload.default_baits,
        default_disinsection_glue=payload.default_disinsection_glue,
        start_date=payload.start_date,
        end_date=payload.end_date,
    )


@app.get("/api/inventory", response_model=list[InventoryOut])
def list_inventory(
    search: str | None = Query(default=None, max_length=200),
    supplier: str | None = Query(default=None, max_length=200),
    unit: str | None = Query(default=None, max_length=30),
    low_stock: bool | None = None,
):
    with Session(engine) as session:
        statement = select(Inventory).order_by(
            Inventory.chemical_name, Inventory.expiry_date, Inventory.id
        )
        if search:
            pattern = f"%{search.strip()}%"
            statement = statement.where(
                or_(
                    Inventory.chemical_name.ilike(pattern),
                    Inventory.batch_number.ilike(pattern),
                )
            )
        if supplier:
            statement = statement.where(Inventory.supplier == supplier.strip())
        if unit:
            statement = statement.where(Inventory.unit == unit.strip())
        if low_stock is not None:
            low_expression = (
                Inventory.quantity < Inventory.initial_quantity * LOW_STOCK_RATIO
            )
            statement = statement.where(
                low_expression if low_stock else ~low_expression
            )
        return [serialize_inventory(row) for row in session.scalars(statement).all()]


@app.post("/api/inventory", response_model=InventoryOut)
def create_inventory(payload: InventoryIn):
    row = Inventory(**payload.model_dump(), initial_quantity=payload.quantity)
    with Session(engine) as session:
        try:
            session.add(row)
            session.commit()
            session.refresh(row)
        except IntegrityError as error:
            session.rollback()
            raise HTTPException(
                status_code=409, detail="inventory batch already exists"
            ) from error
        return serialize_inventory(row)


@app.patch("/api/inventory/{inventory_id}", response_model=InventoryOut)
def update_inventory(inventory_id: int, payload: InventoryUpdate):
    with Session(engine) as session:
        row = session.get(Inventory, inventory_id)
        if row is None:
            raise HTTPException(status_code=404, detail="not found")
        for field, value in payload.model_dump(exclude_unset=True).items():
            setattr(row, field, value)
        try:
            session.commit()
            session.refresh(row)
        except IntegrityError as error:
            session.rollback()
            raise HTTPException(
                status_code=409, detail="constraint violation"
            ) from error
        return serialize_inventory(row)


@app.delete("/api/inventory/{inventory_id}", status_code=204)
def delete_inventory(inventory_id: int):
    with Session(engine) as session:
        row = session.get(Inventory, inventory_id)
        if row is None:
            raise HTTPException(status_code=404, detail="not found")
        linked_usage = session.scalar(
            select(ChemicalUsage.id).where(ChemicalUsage.inventory_id == inventory_id)
        )
        if linked_usage is not None:
            raise HTTPException(status_code=409, detail="inventory has usage history")
        session.delete(row)
        session.commit()
        return Response(status_code=204)


@app.get("/api/treatments", response_model=list[InventoryTreatmentOut])
def list_treatments():
    with Session(engine) as session:
        rows = session.scalars(
            select(Treatment)
            .options(
                selectinload(Treatment.chemical_usages).selectinload(
                    ChemicalUsage.inventory
                )
            )
            .order_by(Treatment.performed_at.desc(), Treatment.id.desc())
        ).all()
        return [serialize_inventory_treatment(row) for row in rows]


@app.post("/api/treatments", response_model=InventoryTreatmentOut)
def create_treatment(payload: TreatmentIn):
    with Session(engine) as session:
        try:
            row = create_treatment_with_inventory(session, payload)
            result = serialize_inventory_treatment(row)
        except InventoryNotFound as error:
            session.rollback()
            raise HTTPException(status_code=404, detail=str(error)) from error
        except InsufficientInventory as error:
            session.rollback()
            raise HTTPException(status_code=409, detail=str(error)) from error
        print(
            json.dumps(
                {
                    "event": "treatment_created",
                    "treatment_id": row.id,
                    "object_id": row.object_id,
                    "chemical_count": len(row.chemical_usages),
                },
                ensure_ascii=False,
            )
        )
        return result


@app.get("/api/objects", response_model=list[ObjectOut])
def list_objects(type: ObjectType | None = None, status: ObjectStatus | None = None):
    with Session(engine) as session:
        statement = select(Object).order_by(Object.id.desc())
        if type is not None:
            statement = statement.where(Object.type == type)
        rows = session.scalars(statement).all()
        if status is not None:
            rows = [row for row in rows if effective_status(row) == status]
        return [serialize_object(row) for row in rows]


@app.post("/api/objects", response_model=ObjectOut)
def create_object(payload: ObjectIn):
    try:
        stored_address, encrypted_address = protect_address(
            payload.type, payload.address
        )
    except PiiEncryptionUnavailable as error:
        raise HTTPException(
            status_code=503, detail="PII encryption unavailable"
        ) from error
    row = Object(
        name=payload.name.strip(),
        address=stored_address,
        encrypted_address=encrypted_address,
        type=payload.type,
        area_sqm=payload.area_sqm,
        contract=_contract_from_input(payload.contract) if payload.contract else None,
        risk_points=payload.risk_points,
        last_treatment_date=payload.last_treatment_date,
        next_treatment_date=payload.next_treatment_date,
        status=payload.status,
    )
    with Session(engine) as session:
        try:
            session.add(row)
            session.commit()
            session.refresh(row)
        except IntegrityError as error:
            session.rollback()
            raise HTTPException(
                status_code=409, detail="contract already exists"
            ) from error
        result = serialize_object(row)
        print(
            json.dumps(
                {"event": "object_created", "object_id": row.id, "type": row.type},
                ensure_ascii=False,
            )
        )
        return result


@app.get("/api/objects/{object_id}", response_model=ObjectOut)
def get_object(
    object_id: int, request: Request, response: Response, show_pii: bool = False
):
    with Session(engine) as session:
        row = session.get(Object, object_id)
        if row is None:
            raise HTTPException(status_code=404, detail="not found")
        if not show_pii or row.type != "apartment":
            return serialize_object(row)
        client_host = request.client.host if request.client else ""
        if client_host not in ("127.0.0.1", "::1"):
            raise HTTPException(status_code=403, detail="PII reveal is localhost only")
        try:
            full_address = reveal_address(row)
        except ValueError as error:
            raise HTTPException(status_code=409, detail="PII is unavailable") from error
        response.headers["Cache-Control"] = "no-store"
        print(
            json.dumps(
                {
                    "timestamp": datetime.now().astimezone().isoformat(),
                    "event": "object_address_revealed",
                    "object_id": row.id,
                },
                ensure_ascii=False,
            )
        )
        return serialize_object(row, address=full_address)


@app.patch("/api/objects/{object_id}", response_model=ObjectOut)
def update_object(object_id: int, payload: ObjectUpdate):
    with Session(engine) as session:
        row = session.get(Object, object_id)
        if row is None:
            raise HTTPException(status_code=404, detail="not found")
        changes = payload.model_dump(exclude_unset=True, exclude={"contract"})
        new_type = changes.get("type", row.type)
        new_address = changes.get("address")
        if new_address is not None or ("type" in changes and new_type != row.type):
            if new_address is None and row.type == "apartment":
                raise HTTPException(
                    status_code=422,
                    detail="address is required when changing apartment type",
                )
            source_address = new_address or row.address
            try:
                protected_address = protect_address(new_type, source_address)
            except PiiEncryptionUnavailable as error:
                raise HTTPException(
                    status_code=503, detail="PII encryption unavailable"
                ) from error
            row.address, row.encrypted_address = protected_address
        for field, value in changes.items():
            if field != "address":
                setattr(row, field, value)
        if "contract" in payload.model_fields_set:
            old_contract = row.contract
            if payload.contract is None:
                row.contract = None
                session.flush()
                if old_contract is not None:
                    session.delete(old_contract)
            elif old_contract is None:
                row.contract = _contract_from_input(payload.contract)
            else:
                old_contract.number = payload.contract.number
                old_contract.price = payload.contract.price
                old_contract.contract_date = payload.contract.contract_date
                old_contract.periodicity = payload.contract.periodicity
                old_contract.service_months = payload.contract.service_months
                old_contract.payment_term_business_days = (
                    payload.contract.payment_term_business_days
                )
                old_contract.default_ksp = payload.contract.default_ksp
                old_contract.default_derat_glue = payload.contract.default_derat_glue
                old_contract.default_baits = payload.contract.default_baits
                old_contract.default_disinsection_glue = (
                    payload.contract.default_disinsection_glue
                )
                old_contract.start_date = payload.contract.start_date
                old_contract.end_date = payload.contract.end_date
        try:
            session.commit()
            session.refresh(row)
        except IntegrityError as error:
            session.rollback()
            raise HTTPException(
                status_code=409, detail="constraint violation"
            ) from error
        return serialize_object(row)


@app.delete("/api/objects/{object_id}", status_code=204)
def delete_object(object_id: int):
    with Session(engine) as session:
        row = session.get(Object, object_id)
        if row is None:
            raise HTTPException(status_code=404, detail="not found")
        if row.clients or row.treatments:
            raise HTTPException(status_code=409, detail="object has related records")
        linked_lead = session.scalar(select(Lead.id).where(Lead.object_id == row.id))
        if linked_lead is not None:
            raise HTTPException(status_code=409, detail="object has related records")
        old_contract = row.contract
        session.delete(row)
        session.flush()
        if old_contract is not None:
            session.delete(old_contract)
        session.commit()
        return Response(status_code=204)


@app.get("/api/objects/{object_id}/treatments", response_model=list[TreatmentOut])
def list_object_treatments(object_id: int):
    with Session(engine) as session:
        if session.get(Object, object_id) is None:
            raise HTTPException(status_code=404, detail="not found")
        rows = session.scalars(
            select(Treatment)
            .where(Treatment.object_id == object_id)
            .order_by(Treatment.performed_at.desc())
        ).all()
        return [serialize_treatment(row) for row in rows]


def _mask_identifier(value: str | None) -> str | None:
    if not value:
        return None
    if len(value) <= 4:
        return "***"
    return f"{value[:2]}{'*' * (len(value) - 4)}{value[-2:]}"


@app.put("/api/objects/{object_id}/billing-client", response_model=BillingClientOut)
def save_billing_client(object_id: int, payload: BillingClientIn):
    encrypted = encrypt_sensitive_mapping(payload.model_dump())
    if encrypted is None:
        raise HTTPException(status_code=503, detail="PII encryption unavailable")
    with Session(engine) as session:
        service_object = session.get(Object, object_id)
        if service_object is None:
            raise HTTPException(status_code=404, detail="not found")
        row = session.scalar(
            select(Client)
            .where(Client.object_id == object_id)
            .order_by(Client.id)
            .limit(1)
        )
        if row is None:
            row = Client(name=payload.name, object_id=object_id)
            session.add(row)
        row.client_type = payload.client_type
        row.name = (
            mask_name(payload.name)
            if payload.client_type == "individual"
            else payload.name
        )
        row.phone = mask_phone(payload.phone) or None
        row.representative = mask_name(payload.representative) or None
        row.representative_role = payload.representative_role
        row.inn_masked = _mask_identifier(payload.inn)
        row.kpp_masked = _mask_identifier(payload.kpp)
        row.registration_number_masked = _mask_identifier(payload.registration_number)
        row.legal_address_masked = (
            mask_address(payload.legal_address) if payload.legal_address else None
        )
        row.bank_details_masked = "***" if payload.bank_details else None
        row.encrypted_requisites = encrypted
        session.commit()
        session.refresh(row)
        return serialize_billing_client(row)


@app.get("/api/objects/{object_id}/billing-client", response_model=BillingClientOut)
def get_billing_client(
    object_id: int, request: Request, response: Response, show_pii: bool = False
):
    with Session(engine) as session:
        row = session.scalar(
            select(Client)
            .where(Client.object_id == object_id)
            .order_by(Client.id)
            .limit(1)
        )
        if row is None:
            raise HTTPException(status_code=404, detail="not found")
        if not show_pii:
            return serialize_billing_client(row)
        client_host = request.client.host if request.client else ""
        if client_host not in ("127.0.0.1", "::1"):
            raise HTTPException(status_code=403, detail="PII reveal is localhost only")
        try:
            values = decrypt_sensitive_mapping(row.encrypted_requisites)
        except ValueError as error:
            raise HTTPException(status_code=409, detail="PII is unavailable") from error
        response.headers["Cache-Control"] = "no-store"
        print(
            json.dumps(
                {
                    "timestamp": datetime.now().astimezone().isoformat(),
                    "event": "billing_requisites_revealed",
                    "object_id": object_id,
                    "client_id": row.id,
                },
                ensure_ascii=False,
            )
        )
        return serialize_billing_client(row, values)


def _contract_or_404(session: Session, contract_id: int) -> Contract:
    contract = session.get(Contract, contract_id)
    if contract is None:
        raise HTTPException(status_code=404, detail="contract not found")
    return contract


@app.post(
    "/api/contracts/{contract_id}/inspection-reports/{period}",
    response_model=InspectionReportOut,
)
def save_inspection_report(contract_id: int, period: str, payload: InspectionReportIn):
    try:
        report_month = parse_month(period)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    with Session(engine) as session:
        contract = _contract_or_404(session, contract_id)
        row = session.scalar(
            select(InspectionReport).where(
                InspectionReport.contract_id == contract_id,
                InspectionReport.report_month == report_month,
            )
        )
        if row is None:
            row = InspectionReport(
                contract=contract,
                report_month=report_month,
                ksp_count=contract.default_ksp,
                derat_glue_count=contract.default_derat_glue,
                bait_count=contract.default_baits,
                rodents_caught=0,
                deratization_result="not_required",
                disinsection_glue_count=contract.default_disinsection_glue,
                insects_caught=0,
                disinsection_result="not_required",
                status="draft",
            )
            session.add(row)
        for field in payload.model_fields_set:
            value = getattr(payload, field)
            if value is not None or field in {"inspection_date", "control_date"}:
                setattr(row, field, value)
        session.commit()
        session.refresh(row)
        return serialize_inspection(row)


def _apply_period_input(
    session: Session, row: ContractPeriod, payload: ContractPeriodIn
) -> None:
    if (
        "transaction_id" in payload.model_fields_set
        and payload.transaction_id is not None
    ):
        transaction = session.get(Transaction, payload.transaction_id)
        contract_object_id = row.contract.object.id if row.contract.object else None
        if (
            transaction is None
            or transaction.kind != "income"
            or transaction.review_required
            or transaction.object_id != contract_object_id
        ):
            raise HTTPException(
                status_code=422,
                detail="transaction must be a confirmed income for this object",
            )
    for field in payload.model_fields_set:
        setattr(row, field, getattr(payload, field))
    if row.work_act_status == "signed" and row.work_act_signed_at is None:
        raise HTTPException(status_code=422, detail="signed act requires signed_at")


@app.post(
    "/api/contracts/{contract_id}/periods/{period}",
    response_model=ContractPeriodOut,
)
def save_contract_period(contract_id: int, period: str, payload: ContractPeriodIn):
    try:
        period_month = parse_month(period)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    with Session(engine) as session:
        contract = _contract_or_404(session, contract_id)
        try:
            row = get_or_create_period(session, contract, period_month)
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        _apply_period_input(session, row, payload)
        session.commit()
        session.refresh(row)
        return serialize_period(row)


@app.patch("/api/contract-periods/{period_id}", response_model=ContractPeriodOut)
def update_contract_period(period_id: int, payload: ContractPeriodIn):
    with Session(engine) as session:
        row = session.get(ContractPeriod, period_id)
        if row is None:
            raise HTTPException(status_code=404, detail="not found")
        _apply_period_input(session, row, payload)
        try:
            session.commit()
            session.refresh(row)
        except IntegrityError as error:
            session.rollback()
            raise HTTPException(
                status_code=409, detail="constraint violation"
            ) from error
        return serialize_period(row)


@app.get("/api/objects/{object_id}/contract-timeline")
def get_contract_timeline(object_id: int) -> list[dict[str, object]]:
    with Session(engine) as session:
        service_object = session.get(Object, object_id)
        if service_object is None:
            raise HTTPException(status_code=404, detail="not found")
        if service_object.contract is None:
            return []
        events: list[dict[str, object]] = []
        for report in service_object.contract.inspection_reports:
            events.append(
                {
                    "date": (report.signed_at or report.created_at).isoformat(),
                    "type": f"inspection_{report.status}",
                    "month": report.report_month.isoformat(),
                }
            )
        for row in service_object.contract.periods:
            events.append(
                {
                    "date": (row.generated_at or row.created_at).isoformat(),
                    "type": (
                        "payment_linked" if row.transaction_id else "period_created"
                    ),
                    "month": row.period_month.isoformat(),
                }
            )
        return sorted(events, key=lambda item: str(item["date"]), reverse=True)


def _document_profile() -> dict[str, str]:
    try:
        payload = json.loads(DOCUMENT_PROFILE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise DocumentTemplateError(
            "company document profile is not configured"
        ) from error
    if not isinstance(payload, dict) or not isinstance(
        payload.get("encrypted_profile"), str
    ):
        raise DocumentTemplateError("company document profile is not configured")
    try:
        decrypted = decrypt_sensitive_mapping(payload["encrypted_profile"])
    except ValueError as error:
        raise DocumentTemplateError(
            "company document profile is unavailable"
        ) from error
    required = {
        "EXECUTOR_BANK_DETAILS",
        "EXECUTOR_INN",
        "EXECUTOR_OGRNIP",
        "TAX_MODE",
    }
    values = {
        str(key): str(value).strip()
        for key, value in decrypted.items()
        if isinstance(value, str)
    }
    if any(not values.get(key) for key in required):
        raise DocumentTemplateError("company document profile is incomplete")
    return values


@app.get("/api/document-profile/status")
def get_document_profile_status() -> dict[str, bool]:
    try:
        _document_profile()
    except DocumentTemplateError:
        return {"configured": False}
    return {"configured": True}


@app.put("/api/document-profile")
def save_document_profile(
    payload: DocumentProfileIn, request: Request
) -> dict[str, str]:
    client_host = request.client.host if request.client else ""
    if client_host not in ("127.0.0.1", "::1"):
        raise HTTPException(
            status_code=403, detail="document profile is localhost only"
        )
    encrypted = encrypt_sensitive_mapping(
        {
            "EXECUTOR_BANK_DETAILS": payload.executor_bank_details,
            "EXECUTOR_INN": payload.executor_inn,
            "EXECUTOR_OGRNIP": payload.executor_ogrnip,
            "TAX_MODE": payload.tax_mode,
        }
    )
    if encrypted is None:
        raise HTTPException(status_code=503, detail="PII encryption unavailable")
    DOCUMENT_PROFILE_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary = DOCUMENT_PROFILE_PATH.with_name(
        f".{DOCUMENT_PROFILE_PATH.name}.{uuid4().hex}.tmp"
    )
    try:
        temporary.write_text(
            json.dumps({"encrypted_profile": encrypted}), encoding="utf-8"
        )
        temporary.replace(DOCUMENT_PROFILE_PATH)
    finally:
        temporary.unlink(missing_ok=True)
    return {"status": "configured"}


def _client_representation(values: dict[str, str | None]) -> str:
    name = values.get("name") or ""
    representative = values.get("representative") or ""
    role = values.get("representative_role") or "представителя"
    if values.get("client_type") == "legal_entity" and representative:
        return f"{name} в лице {role} {representative}"
    if values.get("client_type") == "sole_proprietor":
        return f"Индивидуальный предприниматель {name}"
    return name


def _package_values(
    service_object: Object,
    contract: Contract,
    report: InspectionReport,
    period: ContractPeriod,
    client_values: dict[str, str | None],
) -> dict[str, str]:
    if report.inspection_date is None:
        raise DocumentTemplateError("inspection date is required")
    if period.paid_service_due and period.invoice_date is None:
        raise DocumentTemplateError("invoice date is required")
    if period.paid_service_due and not period.invoice_number:
        raise DocumentTemplateError("invoice number is required")
    price = period.price_snapshot or contract.price
    price_text = f"{Decimal(price):.2f}"
    inspection_date = report.control_date or report.inspection_date
    recommendations = []
    if period.preparations:
        recommendations.append(f"Применённые препараты: {period.preparations}")
    recommendations.extend(period.extra_services or [])
    extra = list(period.extra_services or [])[:2]
    due_date = ""
    if period.invoice_date is not None:
        try:
            due_date = add_business_days(
                period.invoice_date, contract.payment_term_business_days
            ).strftime("%d.%m.%Y")
        except CalendarRangeError as error:
            raise DocumentTemplateError(str(error)) from error
    profile = _document_profile()
    values = {
        "ADDRESS": service_object.address,
        "APPENDIX_NUM": "1",
        "AREA": f"{Decimal(service_object.area_sqm):f}",
        "BAIT_POINTS": str(report.bait_count),
        "BAIT_RESULT": (
            "следов нет" if report.rodents_caught == 0 else "обнаружены следы"
        ),
        "CLIENT_NAME": client_values.get("name") or "",
        "CLIENT_REMARKS": "Претензий нет",
        "CLIENT_REPRESENTATION": _client_representation(client_values),
        "CLIENT_SIGNATURE_ROLE": client_values.get("representative_role") or "Заказчик",
        "CLIENT_TYPE": client_values.get("client_type") or "",
        "CONCLUSION": (
            "Обработка не требуется"
            if report.deratization_result == "not_required"
            and report.disinsection_result == "not_required"
            else "Обработка требуется и выполнена"
        ),
        "CONTRACT_DATE": (
            contract.contract_date.strftime("%d.%m.%Y")
            if contract.contract_date
            else ""
        ),
        "CONTRACT_NUM": contract.number,
        "DIRECTOR_SHORT": client_values.get("representative") or "",
        "INN": client_values.get("inn") or "",
        "INSECT_ACTIVITY_COUNT": str(report.insects_caught),
        "INSECT_ACTIVITY_NOTE": period.infestation_degree,
        "INSECT_GLUE_TRAPS": str(report.disinsection_glue_count),
        "INSECT_TRAP_RESULT": (
            "не обнаружены" if report.insects_caught == 0 else "обнаружены"
        ),
        "INSPECTION_DATE": inspection_date.strftime("%d.%m.%Y"),
        "KSP_COUNT": str(report.ksp_count),
        "KSP_RESULT": (
            "следов нет" if report.rodents_caught == 0 else "обнаружены следы"
        ),
        "OBJECT_NAME": service_object.name,
        "RECOMMENDATIONS": "; ".join(recommendations) or "Нет",
        "RODENT_ACTIVITY_COUNT": str(report.rodents_caught),
        "RODENT_ACTIVITY_NOTE": period.infestation_degree,
        "RODENT_GLUE_TRAPS": str(report.derat_glue_count),
        "RODENT_TRAP_RESULT": (
            "не обнаружены" if report.rodents_caught == 0 else "обнаружены"
        ),
        "ACT_DATE": (period.invoice_date or inspection_date).strftime("%d.%m.%Y"),
        "ACT_NUM": period.invoice_number or "",
        "LINE_TOTAL_1": price_text,
        "LINE_TOTAL_2": "",
        "LINE_TOTAL_3": "",
        "QTY_1": "1",
        "QTY_2": "1" if len(extra) > 0 else "",
        "QTY_3": "1" if len(extra) > 1 else "",
        "SERVICE_1": "Услуги по договору санитарного обслуживания",
        "SERVICE_2": extra[0] if len(extra) > 0 else "",
        "SERVICE_3": extra[1] if len(extra) > 1 else "",
        "TOTAL": price_text,
        "UNIT_1": "усл.",
        "UNIT_2": "усл." if len(extra) > 0 else "",
        "UNIT_3": "усл." if len(extra) > 1 else "",
        "UNIT_PRICE_1": price_text,
        "UNIT_PRICE_2": "",
        "UNIT_PRICE_3": "",
        "WORK_RESULT_AND_SAFETY": ("Работы выполнены в полном объёме. Претензий нет."),
        "INVOICE_DATE": (
            period.invoice_date.strftime("%d.%m.%Y") if period.invoice_date else ""
        ),
        "INVOICE_NUM": period.invoice_number or "",
        "PAYMENT_DUE_DATE": due_date,
        "PRICE": price_text,
        "SERVICE_NAME": "Услуги по договору санитарного обслуживания",
        "TOTAL_WORDS": f"{price_text} рублей",
    }
    values.update(profile)
    return values


@app.post(
    "/api/contract-periods/{period_id}/generate", response_model=ContractPeriodOut
)
def generate_contract_period_package(period_id: int, request: Request):
    client_host = request.client.host if request.client else ""
    if client_host not in ("127.0.0.1", "::1"):
        raise HTTPException(
            status_code=403, detail="document generation is localhost only"
        )
    with Session(engine) as session:
        period = session.get(ContractPeriod, period_id)
        if period is None:
            raise HTTPException(status_code=404, detail="not found")
        contract = period.contract
        service_object = contract.object
        if service_object is None:
            raise HTTPException(status_code=409, detail="contract has no object")
        report = session.scalar(
            select(InspectionReport).where(
                InspectionReport.contract_id == contract.id,
                InspectionReport.report_month == period.period_month,
            )
        )
        client = session.scalar(
            select(Client)
            .where(Client.object_id == service_object.id)
            .order_by(Client.id)
            .limit(1)
        )
        if report is None or client is None:
            raise HTTPException(
                status_code=409, detail="inspection and billing client are required"
            )
        try:
            client_values = decrypt_sensitive_mapping(client.encrypted_requisites)
            values = _package_values(
                service_object, contract, report, period, client_values
            )
            manifest = build_month_package(
                template_dir=DOCUMENT_TEMPLATE_DIR,
                output_root=DOCUMENT_OUTPUT_ROOT,
                object_name=service_object.name,
                period_month=period.period_month,
                paid_service_due=period.paid_service_due,
                values=values,
            )
        except (ValueError, DocumentTemplateError) as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        period.generated_at = datetime.now(UTC)
        period.file_manifest = [
            {
                "version": manifest.version,
                "kind": item.kind,
                "name": item.name,
                "size": item.size,
                "sha256": item.sha256,
            }
            for item in manifest.files
        ]
        session.commit()
        session.refresh(period)
        print(
            json.dumps(
                {
                    "event": "contract_package_generated",
                    "object_id": service_object.id,
                    "contract_id": contract.id,
                    "period_id": period.id,
                    "version": manifest.version,
                },
                ensure_ascii=False,
            )
        )
        return serialize_period(period)


@app.get("/api/contract-periods/{period_id}/files/{file_name}")
def download_contract_period_file(period_id: int, file_name: str, request: Request):
    client_host = request.client.host if request.client else ""
    if client_host not in ("127.0.0.1", "::1"):
        raise HTTPException(status_code=403, detail="document access is localhost only")
    with Session(engine) as session:
        period = session.get(ContractPeriod, period_id)
        if period is None:
            raise HTTPException(status_code=404, detail="not found")
        entry = next(
            (
                item
                for item in period.file_manifest or []
                if item.get("name") == file_name
                and isinstance(item.get("version"), int)
            ),
            None,
        )
        service_object = period.contract.object
        if entry is None or service_object is None:
            raise HTTPException(status_code=404, detail="document not found")
        version = entry.get("version")
        if not isinstance(version, int):
            raise HTTPException(status_code=404, detail="document not found")
        try:
            path = resolve_package_file(
                output_root=DOCUMENT_OUTPUT_ROOT,
                object_name=service_object.name,
                period_month=period.period_month,
                version=version,
                file_name=file_name,
            )
        except DocumentTemplateError as error:
            raise HTTPException(status_code=404, detail="document not found") from error
        if not path.is_file():
            raise HTTPException(status_code=404, detail="document not found")
        return FileResponse(
            path=str(path),
            filename=file_name,
            media_type=(
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            ),
        )


@app.get("/api/transactions", response_model=list[TransactionOut])
def list_transactions():
    with Session(engine) as session:
        rows = session.scalars(
            select(Transaction).order_by(
                Transaction.operation_date.desc(), Transaction.id.desc()
            )
        ).all()
        return [_transaction_out(session, row) for row in rows]


def _transaction_out(session: Session, row: Transaction) -> TransactionOut:
    object_name = None
    if row.object_id is not None:
        service_object = session.get(Object, row.object_id)
        object_name = service_object.name if service_object is not None else None
    return TransactionOut(
        id=row.id,
        source=row.source,
        operation_date=row.operation_date,
        amount=row.amount,
        currency=row.currency,
        counterparty=row.counterparty,
        description=row.description,
        category=row.category,
        channel=row.channel,
        kind=row.kind,
        review_required=row.review_required,
        object_id=row.object_id,
        lead_id=row.lead_id,
        object_name=object_name,
    )


def _validated_transaction_object(
    session: Session, kind: str, object_id: int | None
) -> int | None:
    if object_id is None:
        return None
    if kind != "income":
        raise HTTPException(status_code=422, detail="only income can link object")
    if session.get(Object, object_id) is None:
        raise HTTPException(status_code=404, detail="object not found")
    return object_id


def _transaction_channel(kind: str, channel: str | None) -> str | None:
    if kind != "income":
        return None
    if channel is not None and channel not in CHANNELS:
        raise HTTPException(status_code=422, detail="bad channel")
    return channel


@app.post("/api/transactions", response_model=TransactionOut)
def create_transaction(payload: TransactionIn):
    with Session(engine) as session:
        values = payload.model_dump()
        values["channel"] = _transaction_channel(payload.kind, payload.channel)
        values["object_id"] = _validated_transaction_object(
            session, payload.kind, payload.object_id
        )
        finance_text = f"{payload.description or ''} {payload.counterparty or ''}"
        values["category"] = classify_finance(finance_text) or default_finance_category(
            payload.kind
        )
        row = Transaction(**values)
        session.add(row)
        session.commit()
        session.refresh(row)
        return _transaction_out(session, row)


@app.post("/api/transactions/{tx_id}/classify", response_model=TransactionOut)
def classify_transaction(tx_id: int, payload: ClassifyIn):
    if payload.kind not in ("income", "expense", "own_transfer", "unknown"):
        raise HTTPException(status_code=422, detail="bad kind")
    with Session(engine) as session:
        row = session.get(Transaction, tx_id)
        if row is None:
            raise HTTPException(status_code=404, detail="not found")
        row.kind = payload.kind
        if payload.kind != "income":
            row.object_id = None
        row.review_required = payload.review_required
        if payload.amount is not None:
            row.amount = payload.amount
        finance_text = f"{row.description or ''} {row.counterparty or ''}"
        row.category = classify_finance(finance_text) or default_finance_category(
            payload.kind
        )
        session.commit()
        session.refresh(row)
        return _transaction_out(session, row)


@app.patch("/api/transactions/{tx_id}/object", response_model=TransactionOut)
def link_transaction_object(tx_id: int, payload: TransactionObjectIn):
    with Session(engine) as session:
        row = session.get(Transaction, tx_id)
        if row is None:
            raise HTTPException(status_code=404, detail="not found")
        row.object_id = _validated_transaction_object(
            session, row.kind, payload.object_id
        )
        session.commit()
        session.refresh(row)
        return _transaction_out(session, row)


@app.get("/api/finance/summary", response_model=FinanceSummary)
def finance_summary():
    with Session(engine) as session:
        income = session.scalar(
            select(func.coalesce(func.sum(Transaction.amount), 0)).where(
                Transaction.kind == "income",
                Transaction.review_required == False,
            )
        )
        expense = session.scalar(
            select(func.coalesce(func.sum(Transaction.amount), 0)).where(
                Transaction.kind == "expense",
                Transaction.review_required == False,
            )
        )
        review_count = session.scalar(
            select(func.count()).where(Transaction.review_required == True)
        )
        return FinanceSummary(
            income=income or Decimal("0.00"),
            expense=expense or Decimal("0.00"),
            review_count=int(review_count or 0),
        )


@app.get("/api/analytics/channels", response_model=ChannelAnalyticsOut)
def channel_analytics(start_date: date = Query(), end_date: date = Query()):
    if start_date > end_date:
        raise HTTPException(status_code=422, detail="bad date range")

    with Session(engine) as session:
        rows = session.execute(
            select(
                Transaction.channel,
                func.sum(Transaction.amount),
                func.count(Transaction.id),
            )
            .where(
                Transaction.kind == "income",
                Transaction.operation_date >= start_date,
                Transaction.operation_date <= end_date,
            )
            .group_by(Transaction.channel)
        ).all()

    grouped: dict[str, tuple[Decimal, int]] = {}
    for channel, total, count in rows:
        label = channel.strip() if channel and channel.strip() else "Не указан"
        previous_total, previous_count = grouped.get(label, (Decimal("0.00"), 0))
        grouped[label] = (
            previous_total + Decimal(total),
            previous_count + int(count),
        )

    cents = Decimal("0.01")
    period_total = sum(
        (total for total, _ in grouped.values()), Decimal("0.00")
    ).quantize(cents)
    channels: list[ChannelAnalyticsRow] = []
    for channel, (total, count) in grouped.items():
        rounded_total = total.quantize(cents)
        channels.append(
            {
                "channel": channel,
                "total_amount": rounded_total,
                "count": count,
                "avg_check": (total / count).quantize(cents),
                "share_percent": (
                    (total / period_total * Decimal("100")).quantize(cents)
                    if period_total
                    else Decimal("0.00")
                ),
            }
        )
    channels.sort(key=lambda row: (-row["total_amount"], row["channel"]))
    return {"period_total": period_total, "channels": channels}


@app.get("/api/analytics/dashboard", response_model=DashboardOut)
def dashboard_analytics(start_date: date = Query(), end_date: date = Query()):
    if start_date > end_date:
        raise HTTPException(status_code=422, detail="bad date range")

    with Session(engine) as session:
        transactions = session.scalars(
            select(Transaction).where(
                Transaction.operation_date >= start_date,
                Transaction.operation_date <= end_date,
                Transaction.kind.in_(("income", "expense")),
                Transaction.review_required == False,
            )
        ).all()
        period_start = datetime.combine(start_date, datetime.min.time())
        period_end = datetime.combine(end_date + timedelta(days=1), datetime.min.time())
        lead_date = func.coalesce(Lead.order_at, Lead.created_at)
        leads = session.scalars(
            select(Lead).where(
                lead_date >= period_start,
                lead_date < period_end,
            )
        ).all()
        object_names = {
            row.id: row.name for row in session.scalars(select(Object)).all()
        }

    zero = Decimal("0.00")
    revenue = sum((row.amount for row in transactions if row.kind == "income"), zero)
    expenses = sum((row.amount for row in transactions if row.kind == "expense"), zero)
    profit = revenue - expenses
    margin_pct = profit / revenue * Decimal("100") if revenue else zero
    unassigned_revenue = sum(
        (
            row.amount
            for row in transactions
            if row.kind == "income" and row.object_id is None
        ),
        zero,
    )

    total_leads = len(leads)
    closed_leads = sum(lead.status == "done" for lead in leads)
    conversion_rate = (
        Decimal(closed_leads) / Decimal(total_leads) * Decimal("100")
        if total_leads
        else zero
    )
    average_check = revenue / Decimal(closed_leads) if closed_leads else zero

    daily_values: dict[date, dict[str, Decimal]] = {}
    object_values: dict[int, Decimal] = {}
    service_values: dict[str, Decimal] = {}
    for row in transactions:
        daily_value = daily_values.setdefault(
            row.operation_date, {"revenue": zero, "expenses": zero}
        )
        if row.kind == "income":
            daily_value["revenue"] += row.amount
            category = row.category or default_finance_category("income")
            service_values[category] = service_values.get(category, zero) + row.amount
            if row.object_id is not None:
                object_values[row.object_id] = (
                    object_values.get(row.object_id, zero) + row.amount
                )
        else:
            daily_value["expenses"] += row.amount

    daily = [
        DashboardDaily(
            date=day,
            revenue=_money(values["revenue"]),
            expenses=_money(values["expenses"]),
            profit=_money(values["revenue"] - values["expenses"]),
        )
        for day, values in sorted(daily_values.items())
    ]
    revenue_days = [item for item in daily if Decimal(item.revenue) > zero]
    best_day = (
        max(
            revenue_days,
            key=lambda item: (Decimal(item.revenue), -item.date.toordinal()),
        )
        if revenue_days
        else None
    )
    top_objects = [
        DashboardObject(
            object_id=object_id,
            name=object_names.get(object_id, f"Объект #{object_id}"),
            revenue=_money(total),
        )
        for object_id, total in sorted(
            object_values.items(), key=lambda item: (-item[1], item[0])
        )[:3]
    ]
    top_services = [
        DashboardService(category=category, revenue=_money(total))
        for category, total in sorted(
            service_values.items(), key=lambda item: (-item[1], item[0])
        )[:3]
    ]

    return DashboardOut(
        revenue=_money(revenue),
        expenses=_money(expenses),
        profit=_money(profit),
        margin_pct=_money(margin_pct),
        total_leads=total_leads,
        closed_leads=closed_leads,
        conversion_rate=_money(conversion_rate),
        average_check=_money(average_check),
        best_day=(
            DashboardBestDay(date=best_day.date, revenue=best_day.revenue)
            if best_day is not None
            else None
        ),
        top_objects=top_objects,
        top_services=top_services,
        unassigned_revenue=_money(unassigned_revenue),
        daily=daily,
    )


@app.get("/api/expense-categories", response_model=list[ExpenseCategoryOut])
def list_expense_categories():
    with Session(engine) as session:
        return session.scalars(
            select(ExpenseCategory)
            .where(ExpenseCategory.is_active == True)
            .order_by(ExpenseCategory.id)
        ).all()


@app.post("/api/expense-categories", response_model=ExpenseCategoryOut)
def create_expense_category(payload: ExpenseCategoryIn):
    name = payload.name.strip()
    if not name or len(name) > 100:
        raise HTTPException(status_code=422, detail="bad category name")

    with Session(engine) as session:
        existing = next(
            (
                row
                for row in session.scalars(select(ExpenseCategory)).all()
                if row.name.strip().casefold() == name.casefold()
            ),
            None,
        )
        if existing is not None:
            raise HTTPException(status_code=400, detail="category already exists")

        row = ExpenseCategory(name=name)
        session.add(row)
        try:
            session.commit()
        except IntegrityError as error:
            session.rollback()
            raise HTTPException(
                status_code=400, detail="category already exists"
            ) from error
        session.refresh(row)
        return row


def _bank_row(payload: BankConfirmRowIn) -> BankRow:
    try:
        amount = parse_amount(payload.amount)
    except BankImportError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return BankRow(
        operation_type=payload.operation_type,
        operation_date=payload.operation_date,
        doc_number=payload.doc_number,
        amount=amount,
        description=payload.description,
        payment_purpose=payload.payment_purpose,
        counterparty_name=payload.counterparty_name,
        counterparty_inn=payload.counterparty_inn,
    )


def _money(value: Decimal) -> str:
    return f"{value.quantize(MONEY_QUANTUM):.2f}"


@app.post("/api/bank/preview", response_model=list[BankPreviewOut])
async def bank_preview(file: UploadFile = File()):
    filename = file.filename or ""
    if Path(filename).suffix.casefold() != ".xlsx":
        raise HTTPException(status_code=400, detail="XLSX file required")
    try:
        rows = parse_tbank_xlsx(await file.read())
    except BankImportError as error:
        raise HTTPException(status_code=400, detail=error.as_detail()) from error

    return [
        BankPreviewOut(
            operation_type=row.operation_type,
            operation_date=row.operation_date,
            doc_number=row.doc_number,
            amount=row.amount,
            description=row.description,
            payment_purpose=row.payment_purpose,
            counterparty_name=row.counterparty_name,
            counterparty_inn=row.counterparty_inn,
            counterparty_inn_masked=mask_inn(row.counterparty_inn),
            source_hash=source_hash(row),
            kind=classification.kind,
            category=classification.category,
            channel=classification.channel,
            comment=transaction_comment(row),
            needs_review=classification.needs_review,
            is_transfer=classification.is_transfer,
        )
        for row in rows
        for classification in (classify_bank_transaction(row),)
    ]


@app.post("/api/bank/confirm", response_model=BankConfirmOut)
def bank_confirm(payload: BankConfirmIn):
    source_filename = Path(payload.source_filename).name
    if not source_filename or Path(source_filename).suffix.casefold() != ".xlsx":
        raise HTTPException(status_code=422, detail="bad source filename")

    batch_id = uuid4()
    zero = Decimal("0.00")
    imported = 0
    duplicates = 0
    imported_amounts = {"income": zero, "expense": zero}
    duplicate_amounts = {"income": zero, "expense": zero}
    excluded_amounts = {"income": zero, "expense": zero}
    statement_amounts = {"income": zero, "expense": zero}

    with Session(engine) as session, session.begin():
        active_expense_categories = set(
            session.scalars(
                select(ExpenseCategory.name).where(ExpenseCategory.is_active == True)
            ).all()
        )
        processed: list[tuple[BankRow, ClassificationResult, str | None]] = []
        for item in payload.transactions:
            row = _bank_row(item)
            try:
                classification = classify_bank_transaction(row)
            except BankImportError as error:
                raise HTTPException(status_code=422, detail=str(error)) from error
            if source_hash(row) != item.source_hash:
                raise HTTPException(status_code=422, detail="source hash mismatch")

            category_override = (
                item.category_override.strip() if item.category_override else None
            )
            if classification.needs_review:
                if not item.review_confirmed or not category_override:
                    raise HTTPException(
                        status_code=422, detail="review decision required"
                    )
                allowed_categories = (
                    set(INCOME_CATEGORIES_V1)
                    if classification.kind == "income"
                    else active_expense_categories
                )
                if category_override not in allowed_categories:
                    raise HTTPException(status_code=422, detail="bad category override")
            elif category_override is not None:
                raise HTTPException(
                    status_code=422, detail="category override is not allowed"
                )
            processed.append((row, classification, category_override))

        for row, raw_classification, category_override in processed:
            classification = raw_classification
            kind = classification.kind
            statement_amounts[kind] += row.amount
            if classification.is_transfer:
                excluded_amounts[kind] += row.amount
                continue

            digest = source_hash(row)
            existing = session.scalar(
                select(Transaction.id).where(Transaction.source_hash == digest)
            )
            if existing is not None:
                duplicates += 1
                duplicate_amounts[kind] += row.amount
                continue

            transaction = Transaction(
                source="tbank",
                operation_date=row.operation_date,
                amount=row.amount,
                currency="RUB",
                counterparty=row.counterparty_name or None,
                description=transaction_comment(row) or None,
                category=category_override or classification.category,
                channel=classification.channel,
                entered_by="Артем",
                kind=kind,
                review_required=False,
                source_hash=digest,
                doc_number=row.doc_number or None,
                counterparty_inn=row.counterparty_inn or None,
                import_batch_id=batch_id,
                source_filename=source_filename,
                needs_review=classification.needs_review,
            )
            try:
                with session.begin_nested():
                    session.add(transaction)
                    session.flush()
            except IntegrityError:
                duplicates += 1
                duplicate_amounts[kind] += row.amount
            else:
                imported += 1
                imported_amounts[kind] += row.amount

    credit_total = statement_amounts["income"].quantize(MONEY_QUANTUM)
    debit_total = statement_amounts["expense"].quantize(MONEY_QUANTUM)
    credit_parts = (
        imported_amounts["income"]
        + duplicate_amounts["income"]
        + excluded_amounts["income"]
    ).quantize(MONEY_QUANTUM)
    debit_parts = (
        imported_amounts["expense"]
        + duplicate_amounts["expense"]
        + excluded_amounts["expense"]
    ).quantize(MONEY_QUANTUM)
    return BankConfirmOut(
        imported=imported,
        skipped_duplicates=duplicates,
        batch_id=str(batch_id),
        imported_income_amount=_money(imported_amounts["income"]),
        imported_expense_amount=_money(imported_amounts["expense"]),
        duplicate_income_amount=_money(duplicate_amounts["income"]),
        duplicate_expense_amount=_money(duplicate_amounts["expense"]),
        excluded_credit_amount=_money(excluded_amounts["income"]),
        excluded_debit_amount=_money(excluded_amounts["expense"]),
        statement_credit_total=_money(credit_total),
        statement_debit_total=_money(debit_total),
        credit_reconciled=credit_parts == credit_total,
        debit_reconciled=debit_parts == debit_total,
    )


@app.get("/api/day")
def get_day(day: date = Query(alias="date")):
    with Session(engine) as session:
        rows = session.scalars(
            select(Transaction)
            .where(
                Transaction.operation_date == day,
                Transaction.kind.in_(("income", "expense")),
                Transaction.review_required == False,
            )
            .order_by(Transaction.created_at, Transaction.id)
        ).all()
        active_expense_categories = [
            row.name
            for row in session.scalars(
                select(ExpenseCategory)
                .where(ExpenseCategory.is_active == True)
                .order_by(ExpenseCategory.id)
            ).all()
        ]

        income_total = sum(
            (row.amount for row in rows if row.kind == "income"), Decimal("0")
        )
        expense_total = sum(
            (row.amount for row in rows if row.kind == "expense"), Decimal("0")
        )
        category_pairs = [
            *(("income", category) for category in INCOME_CATEGORIES_V1),
            *(("expense", category) for category in active_expense_categories),
        ]
        for row in rows:
            category = row.category or default_finance_category(row.kind)
            pair = (row.kind, category)
            if pair not in category_pairs:
                category_pairs.append(pair)

        totals = {
            (kind, category): sum(
                (
                    row.amount
                    for row in rows
                    if row.kind == kind
                    and (row.category or default_finance_category(row.kind)) == category
                ),
                Decimal("0"),
            )
            for kind, category in category_pairs
        }
        categories = [
            {"kind": kind, "category": category, "total": total}
            for (kind, category), total in totals.items()
        ]
        entries = [
            {
                "id": row.id,
                "kind": row.kind,
                "category": row.category or default_finance_category(row.kind),
                "amount": row.amount,
                "description": row.description,
                "entered_by": row.entered_by,
                "time": row.created_at.strftime("%H:%M"),
                "source": row.source,
                "can_delete": row.source == "manual" and day == date.today(),
            }
            for row in rows
        ]
        return {
            "income_total": income_total,
            "expense_total": expense_total,
            "balance": income_total - expense_total,
            "categories": categories,
            "entries": entries,
        }


@app.post("/api/day/entry", response_model=TransactionOut)
def create_day_entry(payload: DayEntryIn):
    if payload.kind not in ("income", "expense"):
        raise HTTPException(status_code=422, detail="bad kind")
    if payload.kind == "income" and payload.category not in INCOME_CATEGORIES_V1:
        raise HTTPException(status_code=422, detail="bad category")
    if payload.kind == "expense" and payload.object_id is not None:
        raise HTTPException(status_code=422, detail="only income can link object")
    if payload.amount < 0:
        raise HTTPException(status_code=422, detail="bad amount")

    with Session(engine) as session:
        if payload.kind == "expense":
            expense_category = session.scalar(
                select(ExpenseCategory).where(
                    ExpenseCategory.name == payload.category,
                    ExpenseCategory.is_active == True,
                )
            )
            if expense_category is None:
                raise HTTPException(status_code=422, detail="bad category")
        row = Transaction(
            source="manual",
            operation_date=payload.entry_date or date.today(),
            amount=payload.amount,
            currency="RUB",
            description=payload.comment,
            category=payload.category,
            channel=_transaction_channel(payload.kind, payload.channel),
            entered_by=payload.entered_by,
            kind=payload.kind,
            review_required=False,
            object_id=_validated_transaction_object(
                session, payload.kind, payload.object_id
            ),
        )
        session.add(row)
        session.commit()
        session.refresh(row)
        return _transaction_out(session, row)


@app.delete("/api/transactions/{tx_id}")
def delete_transaction(tx_id: int):
    with Session(engine) as session:
        row = session.get(Transaction, tx_id)
        if row is None:
            raise HTTPException(status_code=404, detail="not found")
        if row.source != "manual" or row.operation_date != date.today():
            raise HTTPException(status_code=403, detail="deletion is not allowed")
        session.delete(row)
        session.commit()
        return {"status": "deleted", "id": tx_id}


@app.get("/api/leads", response_model=list[LeadOut])
def list_leads():
    with Session(engine) as session:
        rows = session.scalars(select(Lead).order_by(Lead.id.desc())).all()
        return [_masked_lead(row) for row in rows]


def _masked_lead(row: Lead) -> LeadOut:
    result = LeadOut.model_validate(row)
    return result.model_copy(
        update={
            "client_name": mask_name(row.client_name) or None,
            "phone": mask_phone(row.phone) or None,
            "address": mask_address(row.address) or None,
        }
    )


@app.get("/api/leads/{lead_id}", response_model=LeadOut)
def get_lead(
    lead_id: int, request: Request, response: Response, show_pii: bool = False
):
    with Session(engine) as session:
        row = session.get(Lead, lead_id)
        if row is None:
            raise HTTPException(status_code=404, detail="not found")
        if not show_pii:
            return _masked_lead(row)
        client_host = request.client.host if request.client else ""
        if client_host not in ("127.0.0.1", "::1"):
            raise HTTPException(status_code=403, detail="PII reveal is localhost only")
        try:
            full_pii = decrypt_pii(row.encrypted_pii)
        except ValueError as error:
            raise HTTPException(status_code=409, detail="PII is unavailable") from error
        print(
            json.dumps(
                {
                    "timestamp": datetime.now().astimezone().isoformat(),
                    "event": "pii_revealed",
                    "lead_id": row.id,
                },
                ensure_ascii=False,
            )
        )
        response.headers["Cache-Control"] = "no-store"
        result = LeadOut.model_validate(row)
        return result.model_copy(
            update={
                "client_name": full_pii["client_name"],
                "phone": full_pii["phone"],
                "address": full_pii["address"],
                "comment": full_pii["comment"],
            }
        )


@app.post("/api/leads/ingest", response_model=LeadOut)
def ingest_lead(payload: RawTextIn):
    if payload.source not in LEAD_SOURCES:
        raise HTTPException(status_code=422, detail="bad lead source")
    if payload.category is not None and payload.category not in INCOME_CATEGORIES_V1:
        raise HTTPException(status_code=422, detail="bad category")
    data = parse_order_text(payload.text)
    with Session(engine) as session:
        if data["external_id"]:
            existing = session.scalar(
                select(Lead).where(Lead.external_id == data["external_id"])
            )
            if existing is not None:
                return _masked_lead(existing)
        protected = protect_lead_pii(data, payload.text)
        row = Lead(
            source=payload.source,
            category=payload.category,
            external_id=data["external_id"] or None,
            order_at=data["order_at"],
            client_name=protected["client_name"],
            phone=protected["phone"],
            address=protected["address"],
            area=data["area"] or None,
            reason=data["reason"] or None,
            comment=protected["comment"],
            amount_note=data["amount_note"] or None,
            contract=data["contract"] or None,
            partner=data["partner"] or None,
            status="new",
            amount=(
                payload.amount
                if payload.amount is not None
                else parse_amount_note(data["amount_note"])
            ),
            execution_date=(
                payload.execution_date
                if payload.execution_date is not None
                else data["order_at"].date() if data["order_at"] else None
            ),
            performed_by="Артём",
            raw_text=protected["raw_text"],
            encrypted_pii=protected["encrypted_pii"],
        )
        session.add(row)
        session.commit()
        session.refresh(row)
        return _masked_lead(row)


@app.patch("/api/leads/{lead_id}", response_model=LeadOut)
def update_lead(lead_id: int, payload: LeadPatchIn):
    changes = payload.model_dump(exclude_unset=True)
    if not changes:
        raise HTTPException(status_code=422, detail="no fields to update")
    if "amount" in changes and changes["amount"] is None:
        raise HTTPException(status_code=422, detail="amount cannot be null")
    if "performed_by" in changes and changes["performed_by"] is None:
        raise HTTPException(status_code=422, detail="performed_by cannot be null")
    if (
        changes.get("category") is not None
        and changes["category"] not in INCOME_CATEGORIES_V1
    ):
        raise HTTPException(status_code=422, detail="bad category")
    if (
        changes.get("performed_by") is not None
        and changes["performed_by"] not in PERFORMERS
    ):
        raise HTTPException(status_code=422, detail="bad performer")

    with Session(engine) as session:
        row = session.get(Lead, lead_id)
        if row is None:
            raise HTTPException(status_code=404, detail="not found")
        object_id = changes.get("object_id")
        if object_id is not None and session.get(Object, object_id) is None:
            raise HTTPException(status_code=404, detail="object not found")
        for field_name, value in changes.items():
            setattr(row, field_name, value)
        session.commit()
        session.refresh(row)
        return _masked_lead(row)


def _ensure_lead_income(session: Session, lead: Lead) -> None:
    if lead.amount <= Decimal("0.00"):
        return
    if lead.execution_date is None:
        raise HTTPException(status_code=422, detail="execution date is required")
    existing = session.scalar(select(Transaction).where(Transaction.lead_id == lead.id))
    if existing is not None:
        return
    session.add(
        Transaction(
            source="lead_auto",
            operation_date=lead.execution_date,
            amount=lead.amount,
            currency="RUB",
            description="Автодоход по выполненной заявке",
            category=lead.category or "Другие работы",
            channel=None,
            entered_by=lead.performed_by,
            kind="income",
            review_required=False,
            object_id=lead.object_id,
            lead_id=lead.id,
        )
    )


@app.post("/api/leads/{lead_id}/status", response_model=LeadOut)
def set_lead_status(lead_id: int, payload: LeadStatusIn):
    if payload.status not in ("new", "in_work", "done", "cancelled"):
        raise HTTPException(status_code=422, detail="bad status")
    with Session(engine) as session:
        row = session.get(Lead, lead_id)
        if row is None:
            raise HTTPException(status_code=404, detail="not found")
        if payload.status == "done":
            _ensure_lead_income(session, row)
        if payload.status == "done" and row.status != "done":
            row.closed_at = datetime.now(UTC)
        elif payload.status != "done":
            row.closed_at = None
        row.status = payload.status
        session.commit()
        session.refresh(row)
        return _masked_lead(row)
