"""move the lead timestamp default to Python

Revision ID: d3a6f8b1c904
Revises: c9f4e2a7b611
Create Date: 2026-08-27 21:10:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "d3a6f8b1c904"
down_revision: str | None = "c9f4e2a7b611"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _set_created_at_default(default: sa.TextClause | None) -> None:
    connection = op.get_bind()
    if connection.dialect.name == "sqlite":
        with op.get_context().autocommit_block():
            connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
        with op.batch_alter_table("leads", recreate="always") as batch_op:
            batch_op.alter_column(
                "created_at",
                existing_type=sa.DateTime(timezone=True),
                existing_nullable=False,
                server_default=default,
            )
        violations = connection.exec_driver_sql("PRAGMA foreign_key_check").all()
        if violations:
            raise RuntimeError("foreign key violations after leads migration")
        with op.get_context().autocommit_block():
            connection.exec_driver_sql("PRAGMA foreign_keys=ON")
            foreign_keys_enabled = connection.exec_driver_sql(
                "PRAGMA foreign_keys"
            ).scalar_one()
            if foreign_keys_enabled != 1:
                raise RuntimeError("foreign key enforcement was not restored")
        return

    op.alter_column(
        "leads",
        "created_at",
        existing_type=sa.DateTime(timezone=True),
        existing_nullable=False,
        server_default=default,
    )


def upgrade() -> None:
    _set_created_at_default(None)


def downgrade() -> None:
    connection = op.get_bind()
    default = (
        sa.text("CURRENT_TIMESTAMP")
        if connection.dialect.name == "sqlite"
        else sa.text("now()")
    )
    _set_created_at_default(default)
