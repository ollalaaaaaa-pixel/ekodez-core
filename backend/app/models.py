from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy import (
    text as sql_text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Transaction(Base):
    __tablename__ = "transactions"
    __table_args__ = (Index("uq_transactions_lead_id", "lead_id", unique=True),)

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
    lead_id: Mapped[int | None] = mapped_column(ForeignKey("leads.id"), nullable=True)
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
    __table_args__ = (
        CheckConstraint(
            "periodicity IS NULL OR periodicity IN ('monthly', 'semiannual', 'custom')",
            name="ck_contracts_periodicity",
        ),
        CheckConstraint(
            "payment_term_business_days > 0",
            name="ck_contracts_payment_term_positive",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    number: Mapped[str] = mapped_column(String(100), unique=True)
    price: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    contract_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    periodicity: Mapped[str | None] = mapped_column(String(20), nullable=True)
    service_months: Mapped[list[int] | None] = mapped_column(JSON, nullable=True)
    payment_term_business_days: Mapped[int] = mapped_column(default=5)
    default_ksp: Mapped[int] = mapped_column(default=5)
    default_derat_glue: Mapped[int] = mapped_column(default=5)
    default_baits: Mapped[int] = mapped_column(default=5)
    default_disinsection_glue: Mapped[int] = mapped_column(default=6)
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    object: Mapped["Object | None"] = relationship(back_populates="contract")
    inspection_reports: Mapped[list["InspectionReport"]] = relationship(
        back_populates="contract", cascade="all, delete-orphan"
    )
    periods: Mapped[list["ContractPeriod"]] = relationship(
        back_populates="contract", cascade="all, delete-orphan"
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

    contract: Mapped[Contract | None] = relationship(back_populates="object")
    clients: Mapped[list["Client"]] = relationship(back_populates="object")
    treatments: Mapped[list["Treatment"]] = relationship(back_populates="object")


class Lead(Base):
    __tablename__ = "leads"
    __table_args__ = (
        CheckConstraint(
            "performed_by IN ('Артём', 'Алексей')",
            name="ck_leads_performed_by",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(50), default="telegram")
    category: Mapped[str | None] = mapped_column(String(100), nullable=True)
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
    amount: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), default=Decimal("0.00"), server_default="0.00"
    )
    execution_date: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    performed_by: Mapped[str] = mapped_column(
        String(50), default="Артём", server_default="Артём"
    )
    raw_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    encrypted_pii: Mapped[str | None] = mapped_column(Text, nullable=True)
    object_id: Mapped[int | None] = mapped_column(
        ForeignKey("objects.id"), nullable=True
    )
    closed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),  # noqa: UP017
    )


class TelegramMasterDraft(Base):
    __tablename__ = "telegram_master_drafts"
    __table_args__ = (
        CheckConstraint(
            "actor_key IN ('owner', 'alexey')",
            name="ck_telegram_master_drafts_actor",
        ),
        CheckConstraint(
            "action IN ('complete', 'reschedule')",
            name="ck_telegram_master_drafts_action",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    actor_key: Mapped[str] = mapped_column(String(20), unique=True)
    lead_id: Mapped[int] = mapped_column(ForeignKey("leads.id"), nullable=False)
    action: Mapped[str] = mapped_column(String(20))
    step: Mapped[str] = mapped_column(String(40))
    payload: Mapped[dict[str, object]] = mapped_column(JSON, default=dict)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),  # noqa: UP017
    )


class SentReport(Base):
    __tablename__ = "sent_reports"
    __table_args__ = (
        CheckConstraint(
            "report_type IN ('auto', 'manual')",
            name="ck_sent_reports_report_type",
        ),
        CheckConstraint("status IN ('sent', 'failed')", name="ck_sent_reports_status"),
        Index(
            "uq_sent_reports_successful_auto_recipient_date",
            "report_date",
            "recipient_key",
            unique=True,
            sqlite_where=sql_text("status = 'sent' AND report_type = 'auto'"),
            postgresql_where=sql_text("status = 'sent' AND report_type = 'auto'"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    report_date: Mapped[date] = mapped_column(Date, index=True)
    report_type: Mapped[str] = mapped_column(String(20))
    recipient_key: Mapped[str] = mapped_column(String(50))
    status: Mapped[str] = mapped_column(String(20))
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Client(Base):
    __tablename__ = "clients"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    encrypted_pii: Mapped[str | None] = mapped_column(Text, nullable=True)
    client_type: Mapped[str | None] = mapped_column(String(30), nullable=True)
    representative: Mapped[str | None] = mapped_column(String(200), nullable=True)
    representative_role: Mapped[str | None] = mapped_column(String(200), nullable=True)
    inn_masked: Mapped[str | None] = mapped_column(String(20), nullable=True)
    kpp_masked: Mapped[str | None] = mapped_column(String(20), nullable=True)
    registration_number_masked: Mapped[str | None] = mapped_column(
        String(30), nullable=True
    )
    legal_address_masked: Mapped[str | None] = mapped_column(String(500), nullable=True)
    bank_details_masked: Mapped[str | None] = mapped_column(Text, nullable=True)
    encrypted_requisites: Mapped[str | None] = mapped_column(Text, nullable=True)
    object_id: Mapped[int] = mapped_column(ForeignKey("objects.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    object: Mapped[Object] = relationship(back_populates="clients")


class InspectionReport(Base):
    __tablename__ = "inspection_reports"
    __table_args__ = (
        UniqueConstraint(
            "contract_id", "report_month", name="uq_inspection_contract_month"
        ),
        CheckConstraint(
            "deratization_result IN ('not_required', 'required')",
            name="ck_inspection_deratization_result",
        ),
        CheckConstraint(
            "disinsection_result IN ('not_required', 'required')",
            name="ck_inspection_disinsection_result",
        ),
        CheckConstraint("status IN ('draft', 'signed')", name="ck_inspection_status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    contract_id: Mapped[int] = mapped_column(
        ForeignKey("contracts.id", ondelete="CASCADE"), index=True
    )
    report_month: Mapped[date] = mapped_column(Date)
    inspection_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    control_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    ksp_count: Mapped[int] = mapped_column(default=5)
    derat_glue_count: Mapped[int] = mapped_column(default=5)
    bait_count: Mapped[int] = mapped_column(default=5)
    rodents_caught: Mapped[int] = mapped_column(default=0)
    deratization_result: Mapped[str] = mapped_column(String(20), default="not_required")
    disinsection_glue_count: Mapped[int] = mapped_column(default=6)
    insects_caught: Mapped[int] = mapped_column(default=0)
    disinsection_result: Mapped[str] = mapped_column(String(20), default="not_required")
    status: Mapped[str] = mapped_column(String(20), default="draft")
    signed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    contract: Mapped[Contract] = relationship(back_populates="inspection_reports")


class ContractPeriod(Base):
    __tablename__ = "contract_periods"
    __table_args__ = (
        UniqueConstraint(
            "contract_id", "period_month", name="uq_contract_period_month"
        ),
        CheckConstraint(
            "work_act_status IN ('draft', 'signed')",
            name="ck_contract_period_work_act_status",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    contract_id: Mapped[int] = mapped_column(
        ForeignKey("contracts.id", ondelete="CASCADE"), index=True
    )
    period_month: Mapped[date] = mapped_column(Date)
    paid_service_due: Mapped[bool] = mapped_column(Boolean)
    price_snapshot: Mapped[Decimal | None] = mapped_column(
        Numeric(14, 2), nullable=True
    )
    preparations: Mapped[str | None] = mapped_column(Text, nullable=True)
    infestation_degree: Mapped[str] = mapped_column(String(100), default="начальная")
    extra_services: Mapped[list[str]] = mapped_column(JSON, default=list)
    invoice_number: Mapped[str | None] = mapped_column(
        String(100), nullable=True, unique=True
    )
    invoice_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    work_act_status: Mapped[str] = mapped_column(String(20), default="draft")
    work_act_signed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    transaction_id: Mapped[int | None] = mapped_column(
        ForeignKey("transactions.id"), nullable=True, unique=True
    )
    generated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    file_manifest: Mapped[list[dict[str, object]]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    contract: Mapped[Contract] = relationship(back_populates="periods")
    transaction: Mapped[Transaction | None] = relationship()


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
