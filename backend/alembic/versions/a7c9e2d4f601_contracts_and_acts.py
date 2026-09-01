"""add contracts, inspection reports, and monthly document periods

Revision ID: a7c9e2d4f601
Revises: f6a8c2d4e701
Create Date: 2026-09-01 09:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a7c9e2d4f601"
down_revision: str | None = "f6a8c2d4e701"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    dialect = op.get_bind().dialect.name
    if dialect == "sqlite":
        op.execute("ALTER TABLE contracts RENAME COLUMN monthly_amount TO price")
    else:
        op.alter_column(
            "contracts",
            "monthly_amount",
            new_column_name="price",
            existing_type=sa.Numeric(14, 2),
            existing_nullable=False,
        )

    contract_columns = (
        sa.Column("contract_date", sa.Date(), nullable=True),
        sa.Column("periodicity", sa.String(20), nullable=True),
        sa.Column("service_months", sa.JSON(), nullable=True),
        sa.Column(
            "payment_term_business_days",
            sa.Integer(),
            nullable=False,
            server_default="5",
        ),
        sa.Column("default_ksp", sa.Integer(), nullable=False, server_default="5"),
        sa.Column(
            "default_derat_glue", sa.Integer(), nullable=False, server_default="5"
        ),
        sa.Column("default_baits", sa.Integer(), nullable=False, server_default="5"),
        sa.Column(
            "default_disinsection_glue",
            sa.Integer(),
            nullable=False,
            server_default="6",
        ),
    )
    for column in contract_columns:
        op.add_column("contracts", column)

    client_columns = (
        sa.Column("client_type", sa.String(30), nullable=True),
        sa.Column("representative", sa.String(200), nullable=True),
        sa.Column("representative_role", sa.String(200), nullable=True),
        sa.Column("inn_masked", sa.String(20), nullable=True),
        sa.Column("kpp_masked", sa.String(20), nullable=True),
        sa.Column("registration_number_masked", sa.String(30), nullable=True),
        sa.Column("legal_address_masked", sa.String(500), nullable=True),
        sa.Column("bank_details_masked", sa.Text(), nullable=True),
        sa.Column("encrypted_requisites", sa.Text(), nullable=True),
    )
    for column in client_columns:
        op.add_column("clients", column)

    op.create_table(
        "inspection_reports",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("contract_id", sa.Integer(), nullable=False),
        sa.Column("report_month", sa.Date(), nullable=False),
        sa.Column("inspection_date", sa.Date(), nullable=True),
        sa.Column("control_date", sa.Date(), nullable=True),
        sa.Column("ksp_count", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("derat_glue_count", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("bait_count", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("rodents_caught", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "deratization_result",
            sa.String(20),
            nullable=False,
            server_default="not_required",
        ),
        sa.Column(
            "disinsection_glue_count",
            sa.Integer(),
            nullable=False,
            server_default="6",
        ),
        sa.Column("insects_caught", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "disinsection_result",
            sa.String(20),
            nullable=False,
            server_default="not_required",
        ),
        sa.Column("status", sa.String(20), nullable=False, server_default="draft"),
        sa.Column("signed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.CheckConstraint(
            "deratization_result IN ('not_required', 'required')",
            name="ck_inspection_deratization_result",
        ),
        sa.CheckConstraint(
            "disinsection_result IN ('not_required', 'required')",
            name="ck_inspection_disinsection_result",
        ),
        sa.CheckConstraint(
            "status IN ('draft', 'signed')", name="ck_inspection_status"
        ),
        sa.ForeignKeyConstraint(["contract_id"], ["contracts.id"], ondelete="CASCADE"),
        sa.UniqueConstraint(
            "contract_id", "report_month", name="uq_inspection_contract_month"
        ),
    )
    op.create_index(
        "ix_inspection_reports_contract_id",
        "inspection_reports",
        ["contract_id"],
    )

    op.create_table(
        "contract_periods",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("contract_id", sa.Integer(), nullable=False),
        sa.Column("period_month", sa.Date(), nullable=False),
        sa.Column("paid_service_due", sa.Boolean(), nullable=False),
        sa.Column("price_snapshot", sa.Numeric(14, 2), nullable=True),
        sa.Column("preparations", sa.Text(), nullable=True),
        sa.Column(
            "infestation_degree",
            sa.String(100),
            nullable=False,
            server_default="начальная",
        ),
        sa.Column("extra_services", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("invoice_number", sa.String(100), nullable=True, unique=True),
        sa.Column("invoice_date", sa.Date(), nullable=True),
        sa.Column(
            "work_act_status",
            sa.String(20),
            nullable=False,
            server_default="draft",
        ),
        sa.Column("work_act_signed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("transaction_id", sa.Integer(), nullable=True, unique=True),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("file_manifest", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.CheckConstraint(
            "work_act_status IN ('draft', 'signed')",
            name="ck_contract_period_work_act_status",
        ),
        sa.ForeignKeyConstraint(["contract_id"], ["contracts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["transaction_id"], ["transactions.id"]),
        sa.UniqueConstraint(
            "contract_id", "period_month", name="uq_contract_period_month"
        ),
    )
    op.create_index(
        "ix_contract_periods_contract_id", "contract_periods", ["contract_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_contract_periods_contract_id", table_name="contract_periods")
    op.drop_table("contract_periods")
    op.drop_index("ix_inspection_reports_contract_id", table_name="inspection_reports")
    op.drop_table("inspection_reports")

    for column_name in (
        "encrypted_requisites",
        "bank_details_masked",
        "legal_address_masked",
        "registration_number_masked",
        "kpp_masked",
        "inn_masked",
        "representative_role",
        "representative",
        "client_type",
    ):
        op.drop_column("clients", column_name)

    for column_name in (
        "default_disinsection_glue",
        "default_baits",
        "default_derat_glue",
        "default_ksp",
        "payment_term_business_days",
        "service_months",
        "periodicity",
        "contract_date",
    ):
        op.drop_column("contracts", column_name)

    dialect = op.get_bind().dialect.name
    if dialect == "sqlite":
        op.execute("ALTER TABLE contracts RENAME COLUMN price TO monthly_amount")
    else:
        op.alter_column(
            "contracts",
            "price",
            new_column_name="monthly_amount",
            existing_type=sa.Numeric(14, 2),
            existing_nullable=False,
        )
