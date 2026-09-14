"""Verified SQLite snapshots outside the repository, before schema changes."""

import hashlib
import logging
import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

BACKUP_ROOT = Path(r"C:\D\Экодез\backups")
logger = logging.getLogger("alembic.runtime.migration")


def sha256(path: Path) -> str:
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def backup_sqlite(source_path: Path) -> Path:
    source_path = source_path.resolve()
    destination = BACKUP_ROOT.resolve()
    if destination.is_relative_to(source_path.parent) or any(
        (parent / ".git").exists() for parent in (destination, *destination.parents)
    ):
        raise RuntimeError(
            "Migration backup must be outside the database directory and Git"
        )
    destination.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    target = destination / f"{source_path.stem}-clients-{stamp}.bak"
    source_hash = sha256(source_path)
    with (
        closing(sqlite3.connect(source_path.as_uri() + "?mode=ro", uri=True)) as source,
        closing(sqlite3.connect(target)) as backup,
    ):
        if source.execute("PRAGMA integrity_check").fetchone() != ("ok",):
            raise RuntimeError("Migration source integrity failed")
        source.backup(backup)
        if backup.execute("PRAGMA integrity_check").fetchone() != ("ok",):
            raise RuntimeError("Migration backup integrity failed")
    logger.info(
        "SQLite backup=%s source_sha256=%s backup_sha256=%s integrity=ok",
        target,
        source_hash,
        sha256(target),
    )
    return target
