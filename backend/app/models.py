from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


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
    object_id: Mapped[int | None] = mapped_column(
        ForeignKey("objects.id"), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    object: Mapped["Object | None"] = relationship()


class ExpenseCategory(Base):
    __tablename__ = "expense_categories"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Contract(Base):
    __tablename__ = "contracts"

    id: Mapped[int] = mapped_column(primary_key=True)
    number: Mapped[str] = mapped_column(String(100), unique=True)
    monthly_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Object(Base):
    __tablename__ = "objects"
    __table_args__ = (
        CheckConstraint(
            "type IN ('restaurant', 'gym', 'kindergarten', 'apartment', "
            "'office', 'other')",
            name="ck_objects_type",
        ),
        CheckConstraint(
            "status IN ('active', 'warranty', 'inactive')",
            name="ck_objects_status",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(300))
    address: Mapped[str] = mapped_column(String(500))
    encrypted_address: Mapped[str | None] = mapped_column(Text, nullable=True)
    type: Mapped[str] = mapped_column(String(30))
    area_sqm: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    contract_id: Mapped[int | None] = mapped_column(
        ForeignKey("contracts.id"), nullable=True, unique=True
    )
    risk_points: Mapped[list[str]] = mapped_column(JSON, default=list)
    last_treatment_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    next_treatment_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="active")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    contract: Mapped[Contract | None] = relationship()
    clients: Mapped[list["Client"]] = relationship(back_populates="object")
    treatments: Mapped[list["Treatment"]] = relationship(back_populates="object")


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
    object_id: Mapped[int | None] = mapped_column(
        ForeignKey("objects.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Client(Base):
    __tablename__ = "clients"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    encrypted_pii: Mapped[str | None] = mapped_column(Text, nullable=True)
    object_id: Mapped[int] = mapped_column(ForeignKey("objects.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    object: Mapped[Object] = relationship(back_populates="clients")


class Treatment(Base):
    __tablename__ = "treatments"

    id: Mapped[int] = mapped_column(primary_key=True)
    lead_id: Mapped[int | None] = mapped_column(ForeignKey("leads.id"), nullable=True)
    object_id: Mapped[int] = mapped_column(ForeignKey("objects.id"))
    chemicals_used: Mapped[list[dict[str, object]]] = mapped_column(JSON, default=list)
    performed_at: Mapped[datetime] = mapped_column(DateTime)
    performed_by: Mapped[str] = mapped_column(String(200))
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    object: Mapped[Object] = relationship(back_populates="treatments")
    chemical_usages: Mapped[list["ChemicalUsage"]] = relationship(
        back_populates="treatment", cascade="all, delete-orphan"
    )


class Inventory(Base):
    __tablename__ = "inventory"
    __table_args__ = (
        UniqueConstraint(
            "chemical_name", "batch_number", name="uq_inventory_chemical_batch"
        ),
        CheckConstraint("quantity >= 0", name="ck_inventory_quantity_nonnegative"),
        CheckConstraint(
            "initial_quantity > 0", name="ck_inventory_initial_quantity_positive"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    chemical_name: Mapped[str] = mapped_column(String(200), index=True)
    quantity: Mapped[Decimal] = mapped_column(Numeric(14, 3))
    initial_quantity: Mapped[Decimal] = mapped_column(Numeric(14, 3))
    unit: Mapped[str] = mapped_column(String(30))
    batch_number: Mapped[str] = mapped_column(String(100))
    expiry_date: Mapped[date] = mapped_column(Date, index=True)
    supplier: Mapped[str] = mapped_column(String(200), index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    chemical_usages: Mapped[list["ChemicalUsage"]] = relationship(
        back_populates="inventory"
    )


class ChemicalUsage(Base):
    __tablename__ = "chemical_usage"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_chemical_usage_quantity_positive"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    inventory_id: Mapped[int] = mapped_column(
        ForeignKey("inventory.id", ondelete="RESTRICT"), index=True
    )
    treatment_id: Mapped[int] = mapped_column(
        ForeignKey("treatments.id", ondelete="CASCADE"), index=True
    )
    quantity: Mapped[Decimal] = mapped_column(Numeric(14, 3))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    inventory: Mapped[Inventory] = relationship(back_populates="chemical_usages")
    treatment: Mapped[Treatment] = relationship(back_populates="chemical_usages")
