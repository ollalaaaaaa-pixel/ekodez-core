"""add master Telegram workflow fields

Revision ID: f6a8c2d4e701
Revises: e4b7c1d9a205
Create Date: 2026-08-31 19:05:00
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "f6a8c2d4e701"
down_revision: str | None = "e4b7c1d9a205"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    dialect = op.get_bind().dialect.name
    amount_column = sa.Column(
        "amount",
        sa.Numeric(14, 2),
        nullable=False,
        server_default="0.00",
    )
    execution_date_column = sa.Column("execution_date", sa.Date(), nullable=True)
    performer_column = sa.Column(
        "performed_by",
        sa.String(50),
        nullable=False,
        server_default="Артём",
    )
    if dialect == "sqlite":
        # Native ADD COLUMN avoids rebuilding parent tables while treatments
        # and other existing rows still reference them.
        op.add_column("leads", amount_column)
        op.add_column("leads", execution_date_column)
        op.add_column("leads", performer_column)
        op.create_index("ix_leads_execution_date", "leads", ["execution_date"])
        op.execute(
            "CREATE TRIGGER ck_leads_performed_by_insert "
            "BEFORE INSERT ON leads WHEN NEW.performed_by NOT IN ('Артём', 'Алексей') "
            "BEGIN SELECT RAISE(ABORT, 'ck_leads_performed_by'); END"
        )
        op.execute(
            "CREATE TRIGGER ck_leads_performed_by_update "
            "BEFORE UPDATE OF performed_by ON leads "
            "WHEN NEW.performed_by NOT IN ('Артём', 'Алексей') "
            "BEGIN SELECT RAISE(ABORT, 'ck_leads_performed_by'); END"
        )
        op.execute(
            "ALTER TABLE transactions ADD COLUMN lead_id INTEGER "
            "REFERENCES leads(id)"
        )
        op.create_index(
            "uq_transactions_lead_id", "transactions", ["lead_id"], unique=True
        )
    else:
        with op.batch_alter_table("leads") as batch_op:
            batch_op.add_column(amount_column)
            batch_op.add_column(execution_date_column)
            batch_op.add_column(performer_column)
            batch_op.create_check_constraint(
                "ck_leads_performed_by",
                "performed_by IN ('Артём', 'Алексей')",
            )
            batch_op.create_index(
                "ix_leads_execution_date", ["execution_date"], unique=False
            )

        with op.batch_alter_table("transactions") as batch_op:
            batch_op.add_column(sa.Column("lead_id", sa.Integer(), nullable=True))
            batch_op.create_foreign_key(
                "fk_transactions_lead_id_leads", "leads", ["lead_id"], ["id"]
            )
            batch_op.create_index("uq_transactions_lead_id", ["lead_id"], unique=True)

    op.create_table(
        "telegram_master_drafts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("actor_key", sa.String(20), nullable=False),
        sa.Column("lead_id", sa.Integer(), nullable=False),
        sa.Column("action", sa.String(20), nullable=False),
        sa.Column("step", sa.String(40), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "actor_key IN ('owner', 'alexey')",
            name="ck_telegram_master_drafts_actor",
        ),
        sa.CheckConstraint(
            "action IN ('complete', 'reschedule')",
            name="ck_telegram_master_drafts_action",
        ),
        sa.ForeignKeyConstraint(["lead_id"], ["leads.id"]),
        sa.UniqueConstraint("actor_key"),
    )


def downgrade() -> None:
    op.drop_table("telegram_master_drafts")

    dialect = op.get_bind().dialect.name
    if dialect == "sqlite":
        op.drop_index("uq_transactions_lead_id", table_name="transactions")
        op.drop_column("transactions", "lead_id")
        op.execute("DROP TRIGGER IF EXISTS ck_leads_performed_by_update")
        op.execute("DROP TRIGGER IF EXISTS ck_leads_performed_by_insert")
        op.drop_index("ix_leads_execution_date", table_name="leads")
        op.drop_column("leads", "performed_by")
        op.drop_column("leads", "execution_date")
        op.drop_column("leads", "amount")
        return

    with op.batch_alter_table("transactions") as batch_op:
        batch_op.drop_index("uq_transactions_lead_id")
        batch_op.drop_constraint("fk_transactions_lead_id_leads", type_="foreignkey")
        batch_op.drop_column("lead_id")

    with op.batch_alter_table("leads") as batch_op:
        batch_op.drop_index("ix_leads_execution_date")
        batch_op.drop_constraint("ck_leads_performed_by", type_="check")
        batch_op.drop_column("performed_by")
        batch_op.drop_column("execution_date")
        batch_op.drop_column("amount")
