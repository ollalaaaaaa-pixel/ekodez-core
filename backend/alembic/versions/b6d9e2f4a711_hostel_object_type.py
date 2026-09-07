"""add hostel object type

Revision ID: b6d9e2f4a711
Revises: f8c1d2e3a409
"""

from collections.abc import Sequence

from alembic import op

revision: str = "b6d9e2f4a711"
down_revision: str | None = "f8c1d2e3a409"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _replace_type_constraint(allowed_types: str) -> None:
    connection = op.get_bind()
    is_sqlite = connection.dialect.name == "sqlite"
    if is_sqlite:
        with op.get_context().autocommit_block():
            connection.exec_driver_sql("PRAGMA foreign_keys=OFF")

    with op.batch_alter_table("objects", recreate="always") as batch_op:
        batch_op.drop_constraint("ck_objects_type", type_="check")
        batch_op.create_check_constraint(
            "ck_objects_type", f"type IN ({allowed_types})"
        )

    if is_sqlite:
        violations = connection.exec_driver_sql("PRAGMA foreign_key_check").all()
        if violations:
            raise RuntimeError("foreign key violations after objects migration")
        with op.get_context().autocommit_block():
            connection.exec_driver_sql("PRAGMA foreign_keys=ON")
            if connection.exec_driver_sql("PRAGMA foreign_keys").scalar_one() != 1:
                raise RuntimeError("foreign key enforcement was not restored")


def upgrade() -> None:
    _replace_type_constraint(
        "'restaurant', 'gym', 'kindergarten', 'apartment', "
        "'office', 'hostel', 'other'"
    )


def downgrade() -> None:
    _replace_type_constraint(
        "'restaurant', 'gym', 'kindergarten', 'apartment', 'office', 'other'"
    )
