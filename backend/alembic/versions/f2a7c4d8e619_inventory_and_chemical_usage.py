"""add inventory and normalized chemical usage

Revision ID: f2a7c4d8e619
Revises: d1e6f9a3b407
Create Date: 2026-08-26 03:20:00
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "f2a7c4d8e619"
down_revision: str | None = "d1e6f9a3b407"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "inventory",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("chemical_name", sa.String(length=200), nullable=False),
        sa.Column("quantity", sa.Numeric(14, 3), nullable=False),
        sa.Column("initial_quantity", sa.Numeric(14, 3), nullable=False),
        sa.Column("unit", sa.String(length=30), nullable=False),
        sa.Column("batch_number", sa.String(length=100), nullable=False),
        sa.Column("expiry_date", sa.Date(), nullable=False),
        sa.Column("supplier", sa.String(length=200), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now()
        ),
        sa.CheckConstraint("quantity >= 0", name="ck_inventory_quantity_nonnegative"),
        sa.CheckConstraint(
            "initial_quantity > 0", name="ck_inventory_initial_quantity_positive"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "chemical_name", "batch_number", name="uq_inventory_chemical_batch"
        ),
    )
    op.create_index("ix_inventory_chemical_name", "inventory", ["chemical_name"])
    op.create_index("ix_inventory_expiry_date", "inventory", ["expiry_date"])
    op.create_index("ix_inventory_supplier", "inventory", ["supplier"])
    op.create_table(
        "chemical_usage",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("inventory_id", sa.Integer(), nullable=False),
        sa.Column("treatment_id", sa.Integer(), nullable=False),
        sa.Column("quantity", sa.Numeric(14, 3), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now()
        ),
        sa.CheckConstraint("quantity > 0", name="ck_chemical_usage_quantity_positive"),
        sa.ForeignKeyConstraint(
            ["inventory_id"], ["inventory.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["treatment_id"], ["treatments.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_chemical_usage_inventory_id", "chemical_usage", ["inventory_id"]
    )
    op.create_index(
        "ix_chemical_usage_treatment_id", "chemical_usage", ["treatment_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_chemical_usage_treatment_id", table_name="chemical_usage")
    op.drop_index("ix_chemical_usage_inventory_id", table_name="chemical_usage")
    op.drop_table("chemical_usage")
    op.drop_index("ix_inventory_supplier", table_name="inventory")
    op.drop_index("ix_inventory_expiry_date", table_name="inventory")
    op.drop_index("ix_inventory_chemical_name", table_name="inventory")
    op.drop_table("inventory")
