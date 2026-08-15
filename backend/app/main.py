import os
from datetime import date, datetime
from decimal import Decimal

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.orm import Session

from app.finance_categories import classify_finance
from app.lead_parser import parse_order_text
from app.models import Lead, Transaction
from app.tg_poller import start_poller

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
    return {"status": "ok"}


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


@app.post("/api/transactions", response_model=TransactionOut)
def create_transaction(payload: TransactionIn):
    with Session(engine) as session:
        values = payload.model_dump()
        finance_text = f"{payload.description or ''} {payload.counterparty or ''}"
        values["category"] = classify_finance(finance_text) or "Прочее"
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
        row.category = classify_finance(finance_text) or "Прочее"
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
            income=income, expense=expense, review_count=review_count
        )


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
