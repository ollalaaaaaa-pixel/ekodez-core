"""monthly auto acts

Revision ID: f8c1d2e3a409
Revises: a7c9e2d4f601
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "f8c1d2e3a409"
down_revision: str | None = "a7c9e2d4f601"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "contracts", sa.Column("inspection_price", sa.Numeric(14, 2), nullable=True)
    )
    op.add_column(
        "contract_periods",
        sa.Column("treatment_invoice_number", sa.String(100), nullable=True),
    )
    op.create_index(
        "uq_contract_periods_treatment_invoice_number",
        "contract_periods",
        ["treatment_invoice_number"],
        unique=True,
    )
    op.add_column(
        "contract_periods",
        sa.Column("treatment_price_snapshot", sa.Numeric(14, 2), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("contract_periods", "treatment_price_snapshot")
    op.drop_index(
        "uq_contract_periods_treatment_invoice_number",
        table_name="contract_periods",
    )
    op.drop_column("contract_periods", "treatment_invoice_number")
    op.drop_column("contracts", "inspection_price")
