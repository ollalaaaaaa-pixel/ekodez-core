"""Finance categories, immutable bank mapping, tags and client backfill."""

# ruff: noqa: E501

import sqlalchemy as sa

from alembic import op

revision = "e0a4c7b9d125"
down_revision = "d9f3b6a8c014"
branch_labels = None
depends_on = None

INCOME = (
    "Химчистка",
    "Дезинсекция",
    "Дератизация",
    "Дезинфекция",
    "Обработка от клещей",
    "Клининг",
    "Юридические клиенты",
    "Доход от агрегаторов",
    "Плесень",
    "Другие работы",
)
BANK_EXPENSES = (
    "Материалы и химия",
    "Налоги и взносы",
    "Банковские комиссии",
    "Прочее",
)


def upgrade() -> None:
    db = op.get_bind()
    op.create_table(
        "transaction_categories",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("title", sa.String(100), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("sort_order", sa.Integer, nullable=False),
        sa.Column("is_active", sa.Boolean, nullable=False),
        sa.UniqueConstraint("kind", "title", name="uq_category_kind_title"),
        sa.CheckConstraint("kind IN ('income', 'expense')", name="ck_category_kind"),
        sa.CheckConstraint("sort_order >= 0", name="ck_category_sort_order"),
    )
    op.create_table(
        "bank_category_mappings",
        sa.Column("kind", sa.String(20), primary_key=True),
        sa.Column("legacy_title", sa.String(100), primary_key=True),
        sa.Column(
            "category_id",
            sa.Integer,
            sa.ForeignKey("transaction_categories.id"),
            nullable=False,
        ),
    )
    values: dict[tuple[str, str], bool] = {("income", title): True for title in INCOME}
    for title, active in db.execute(
        sa.text("SELECT name,is_active FROM expense_categories ORDER BY id")
    ):
        values[("expense", title)] = bool(active)
    for title in BANK_EXPENSES:
        values.setdefault(("expense", title), True)
    for kind, title in db.execute(
        sa.text(
            "SELECT DISTINCT kind,category FROM transactions WHERE kind IN ('income','expense') AND category IS NOT NULL"
        )
    ):
        values.setdefault((kind, title), False)
    for order, ((kind, title), active) in enumerate(values.items()):
        category_id = order + 1
        db.execute(
            sa.text(
                "INSERT INTO transaction_categories(id,title,kind,sort_order,is_active) VALUES (:id,:title,:kind,:order,:active)"
            ),
            {
                "id": category_id,
                "title": title,
                "kind": kind,
                "order": order,
                "active": active,
            },
        )
        db.execute(
            sa.text(
                "INSERT INTO bank_category_mappings(kind,legacy_title,category_id) VALUES (:kind,:title,:id)"
            ),
            {"kind": kind, "title": title, "id": category_id},
        )
    if db.dialect.name == "sqlite":
        db.exec_driver_sql(
            "ALTER TABLE transactions ADD COLUMN category_id INTEGER REFERENCES transaction_categories(id)"
        )
        db.exec_driver_sql(
            "ALTER TABLE transactions ADD COLUMN tags JSON NOT NULL DEFAULT '[]'"
        )
    else:
        op.add_column(
            "transactions",
            sa.Column(
                "category_id",
                sa.Integer,
                sa.ForeignKey("transaction_categories.id"),
                nullable=True,
            ),
        )
        op.add_column(
            "transactions",
            sa.Column("tags", sa.JSON, nullable=False, server_default="[]"),
        )
    op.create_index("ix_transactions_category_id", "transactions", ["category_id"])
    db.execute(
        sa.text(
            "UPDATE transactions SET category_id=(SELECT category_id FROM bank_category_mappings m WHERE m.kind=transactions.kind AND m.legacy_title=transactions.category)"
        )
    )
    missing = db.scalar(
        sa.text(
            "SELECT count(*) FROM transactions WHERE category IS NOT NULL AND kind IN ('income','expense') AND category_id IS NULL"
        )
    )
    if missing:
        raise RuntimeError("Finance migration: unmapped transaction categories")
    if (
        db.dialect.name == "sqlite"
        and db.exec_driver_sql("PRAGMA foreign_key_check").all()
    ):
        raise RuntimeError("Finance migration: foreign key violation")


def downgrade() -> None:
    raise RuntimeError("Restore verified backup to preserve category and tag history")
