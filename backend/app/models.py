from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import Boolean, Date, DateTime, Numeric, String, Text, Uuid, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Transaction(Base):
    __tablename__ = "transactions"

    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(50))
    operation_date: Mapped[date] = mapped_column(Date)
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    currency: Mapped[str] = mapped_column(String(3), default="RUB")
    counterparty: Mapped[str | None] = mapped_column(String(300), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    category: Mapped[str | None] = mapped_column(String(100), nullable=True)
    channel: Mapped[str | None] = mapped_column(String(50), nullable=True)
    entered_by: Mapped[str] = mapped_column(String(50), default="Артем")
    kind: Mapped[str] = mapped_column(String(20), default="unknown")
    review_required: Mapped[bool] = mapped_column(Boolean, default=True)
    source_hash: Mapped[str | None] = mapped_column(
        String(64), nullable=True, unique=True, index=True
    )
    doc_number: Mapped[str | None] = mapped_column(String(50), nullable=True)
    counterparty_inn: Mapped[str | None] = mapped_column(String(20), nullable=True)
    import_batch_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    source_filename: Mapped[str | None] = mapped_column(String(255), nullable=True)
    needs_review: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class ExpenseCategory(Base):
    __tablename__ = "expense_categories"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Lead(Base):
    __tablename__ = "leads"

    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(50), default="telegram")
    external_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    order_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    client_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    address: Mapped[str | None] = mapped_column(String(500), nullable=True)
    area: Mapped[str | None] = mapped_column(String(200), nullable=True)
    reason: Mapped[str | None] = mapped_column(String(300), nullable=True)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    amount_note: Mapped[str | None] = mapped_column(String(300), nullable=True)
    contract: Mapped[str | None] = mapped_column(String(50), nullable=True)
    partner: Mapped[str | None] = mapped_column(String(200), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="new")
    raw_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    encrypted_pii: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
