import os
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import TypedDict
from uuid import uuid4

from dotenv import load_dotenv
from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

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
from app.channels import CHANNELS
from app.finance_categories import (
    INCOME_CATEGORIES_V1,
    classify_finance,
    default_finance_category,
)
from app.lead_parser import parse_order_text
from app.models import ExpenseCategory, Lead, Transaction
from app.tg_poller import poller_started, start_poller

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "")

engine = create_engine(DATABASE_URL)

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


class FinanceSummary(BaseModel):
    income: Decimal
    expense: Decimal
    review_count: int


class ClassifyIn(BaseModel):
    kind: str
    review_required: bool = False
    amount: Decimal | None = None


class DayEntryIn(BaseModel):
    model_config = {"populate_by_name": True}

    kind: str
    category: str
    channel: str | None = None
    amount: Decimal
    comment: str | None = None
    entered_by: str = "Артем"
    entry_date: date | None = Field(default=None, alias="date")


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
    amount: str
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


class RawTextIn(BaseModel):
    text: str


class LeadStatusIn(BaseModel):
    status: str


@app.get("/health")
def health():
    return {
        "status": "ok",
        "telegram": "started" if poller_started() else "stopped",
    }


@app.get("/health/db")
def health_db():
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    return {"status": "ok", "database": "connected"}


@app.get("/api/transactions", response_model=list[TransactionOut])
def list_transactions():
    with Session(engine) as session:
        return session.scalars(
            select(Transaction).order_by(
                Transaction.operation_date.desc(), Transaction.id.desc()
            )
        ).all()


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
        finance_text = f"{payload.description or ''} {payload.counterparty or ''}"
        values["category"] = classify_finance(finance_text) or default_finance_category(
            payload.kind
        )
        row = Transaction(**values)
        session.add(row)
        session.commit()
        session.refresh(row)
        return row


@app.post("/api/transactions/{tx_id}/classify", response_model=TransactionOut)
def classify_transaction(tx_id: int, payload: ClassifyIn):
    if payload.kind not in ("income", "expense", "own_transfer", "unknown"):
        raise HTTPException(status_code=422, detail="bad kind")
    with Session(engine) as session:
        row = session.get(Transaction, tx_id)
        if row is None:
            raise HTTPException(status_code=404, detail="not found")
        row.kind = payload.kind
        row.review_required = payload.review_required
        if payload.amount is not None:
            row.amount = payload.amount
        finance_text = f"{row.description or ''} {row.counterparty or ''}"
        row.category = classify_finance(finance_text) or default_finance_category(
            payload.kind
        )
        session.commit()
        session.refresh(row)
        return row


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
        raise HTTPException(status_code=400, detail=str(error)) from error

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
        )
        session.add(row)
        session.commit()
        session.refresh(row)
        return row


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
        return session.scalars(select(Lead).order_by(Lead.id.desc())).all()


@app.post("/api/leads/ingest", response_model=LeadOut)
def ingest_lead(payload: RawTextIn):
    data = parse_order_text(payload.text)
    with Session(engine) as session:
        if data["external_id"]:
            existing = session.scalar(
                select(Lead).where(Lead.external_id == data["external_id"])
            )
            if existing is not None:
                return existing
        row = Lead(
            source="telegram",
            external_id=data["external_id"] or None,
            order_at=data["order_at"],
            client_name=data["client_name"] or None,
            phone=data["phone"] or None,
            address=data["address"] or None,
            area=data["area"] or None,
            reason=data["reason"] or None,
            comment=data["comment"] or None,
            amount_note=data["amount_note"] or None,
            contract=data["contract"] or None,
            partner=data["partner"] or None,
            status="new",
            raw_text=payload.text,
        )
        session.add(row)
        session.commit()
        session.refresh(row)
        return row


@app.post("/api/leads/{lead_id}/status", response_model=LeadOut)
def set_lead_status(lead_id: int, payload: LeadStatusIn):
    if payload.status not in ("new", "in_work", "done", "cancelled"):
        raise HTTPException(status_code=422, detail="bad status")
    with Session(engine) as session:
        row = session.get(Lead, lead_id)
        if row is None:
            raise HTTPException(status_code=404, detail="not found")
        row.status = payload.status
        session.commit()
        session.refresh(row)
        return row
