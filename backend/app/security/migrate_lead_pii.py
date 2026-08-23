import argparse
import os
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.models import Lead
from app.security.pii import protect_lead_pii


@dataclass(frozen=True)
class MigrationResult:
    backup_path: str
    migrated_count: int


def load_pii_environment(env_path: str) -> None:
    load_dotenv(env_path, override=False)


def migrate_sqlite_database(database_path: str, backup_dir: str) -> MigrationResult:
    if not os.getenv("PII_FERNET_KEY", "").strip():
        raise RuntimeError("PII_FERNET_KEY is required for legacy migration")

    source = Path(database_path).resolve()
    if not source.is_file():
        raise FileNotFoundError("SQLite database not found")
    destination_dir = Path(backup_dir).resolve()
    destination_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    backup = destination_dir / f"ekodez.pre-pii-backup.{timestamp}.db"
    if backup.exists():
        raise RuntimeError("PII backup destination already exists")
    source_uri = f"file:{source.as_posix()}?mode=ro"
    with (
        closing(sqlite3.connect(source_uri, uri=True)) as source_connection,
        closing(sqlite3.connect(backup)) as backup_connection,
    ):
        source_connection.backup(backup_connection)
        integrity = backup_connection.execute("PRAGMA integrity_check").fetchone()
        backup_connection.commit()
    if integrity != ("ok",):
        backup.unlink(missing_ok=True)
        raise RuntimeError("PII backup verification failed")

    engine = create_engine(f"sqlite:///{source.as_posix()}")
    migrated_count = 0
    try:
        with Session(engine) as session, session.begin():
            rows = session.scalars(
                select(Lead).where(Lead.encrypted_pii.is_(None))
            ).all()
            for row in rows:
                protected = protect_lead_pii(
                    {
                        "client_name": row.client_name,
                        "phone": row.phone,
                        "address": row.address,
                        "comment": row.comment,
                    },
                    row.raw_text or "",
                )
                if protected["encrypted_pii"] is None:
                    raise RuntimeError("PII encryption is unavailable")
                row.client_name = protected["client_name"]
                row.phone = protected["phone"]
                row.address = protected["address"]
                row.comment = protected["comment"]
                row.raw_text = protected["raw_text"]
                row.encrypted_pii = protected["encrypted_pii"]
                migrated_count += 1
    finally:
        engine.dispose()
    return MigrationResult(str(backup), migrated_count)


def main() -> None:
    load_pii_environment(str(Path(__file__).resolve().parents[2] / ".env"))
    parser = argparse.ArgumentParser(description="Mask legacy lead PII")
    parser.add_argument("database_path")
    parser.add_argument("backup_dir")
    args = parser.parse_args()
    result = migrate_sqlite_database(args.database_path, args.backup_dir)
    print(f"legacy PII migrated: {result.migrated_count}; backup created")


if __name__ == "__main__":
    main()
