"""add central object model

Revision ID: c7d4e8f1a205
Revises: b3f2a7c9d411
Create Date: 2026-08-23 23:55:00
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c7d4e8f1a205"
down_revision: str | None = "b3f2a7c9d411"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "contracts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("number", sa.String(length=100), nullable=False),
        sa.Column("monthly_amount", sa.Numeric(14, 2), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=True),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now()
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("number"),
    )
    op.create_table(
        "objects",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=300), nullable=False),
        sa.Column("address", sa.String(length=500), nullable=False),
        sa.Column("encrypted_address", sa.Text(), nullable=True),
        sa.Column("type", sa.String(length=30), nullable=False),
        sa.Column("area_sqm", sa.Numeric(12, 2), nullable=False),
        sa.Column("contract_id", sa.Integer(), nullable=True),
        sa.Column("risk_points", sa.JSON(), nullable=False),
        sa.Column("last_treatment_date", sa.Date(), nullable=True),
        sa.Column("next_treatment_date", sa.Date(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now()
        ),
        sa.CheckConstraint(
            "status IN ('active', 'warranty', 'inactive')",
            name="ck_objects_status",
        ),
        sa.CheckConstraint(
            "type IN ('restaurant', 'gym', 'kindergarten', 'apartment', "
            "'office', 'other')",
            name="ck_objects_type",
        ),
        sa.ForeignKeyConstraint(["contract_id"], ["contracts.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "clients",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("phone", sa.String(length=50), nullable=True),
        sa.Column("encrypted_pii", sa.Text(), nullable=True),
        sa.Column("object_id", sa.Integer(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now()
        ),
        sa.ForeignKeyConstraint(["object_id"], ["objects.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("leads") as batch_op:
        batch_op.add_column(sa.Column("object_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            "fk_leads_object_id_objects", "objects", ["object_id"], ["id"]
        )
    op.create_table(
        "treatments",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("lead_id", sa.Integer(), nullable=True),
        sa.Column("object_id", sa.Integer(), nullable=False),
        sa.Column("chemicals_used", sa.JSON(), nullable=False),
        sa.Column("performed_at", sa.DateTime(), nullable=False),
        sa.Column("performed_by", sa.String(length=200), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now()
        ),
        sa.ForeignKeyConstraint(["lead_id"], ["leads.id"]),
        sa.ForeignKeyConstraint(["object_id"], ["objects.id"]),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("treatments")
    with op.batch_alter_table("leads") as batch_op:
        batch_op.drop_constraint("fk_leads_object_id_objects", type_="foreignkey")
        batch_op.drop_column("object_id")
    op.drop_table("clients")
    op.drop_table("objects")
    op.drop_table("contracts")
