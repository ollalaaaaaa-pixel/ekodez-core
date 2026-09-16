"""Run only after the owner's explicit 'импортируй историю' command."""

import argparse
import json
import os
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy.orm import Session

from app.db import create_app_engine
from app.gnom_parser import GnomError
from app.gnom_scheduler import IMPORT_ROOT
from app.gnom_service import analytics, import_file
from app.migration_backup import backup_sqlite


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--confirm", required=True, choices=["импортируй историю"])
    parser.parse_args()
    destination = Path(r"C:\D\Экодез\analysis\gnom-history-2026-09.md")
    if destination.exists():
        raise GnomError("Отчёт уже существует; сохраните предыдущую версию")
    if not IMPORT_ROOT.is_dir():
        raise GnomError("Папка импорта отсутствует")
    load_dotenv()
    engine = create_app_engine(os.environ["DATABASE_URL"])
    if engine.dialect.name == "sqlite" and engine.url.database:
        backup_sqlite(Path(engine.url.database))
    for path in sorted(IMPORT_ROOT.iterdir()):
        if (
            not path.is_file()
            or path.is_symlink()
            or path.suffix.lower() not in {".csv", ".xlsx", ".xls"}
        ):
            continue
        if not path.resolve().is_relative_to(IMPORT_ROOT.resolve()):
            continue
        with path.open("rb") as stream:
            import_file(
                engine, stream.read(20 * 1024 * 1024 + 1), path.name, authorized=True
            )
    with Session(engine) as session:
        report = analytics(session)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        "# История CRM Гном\n\nОбезличенные агрегаты.\n\n```json\n"
        + json.dumps(report, ensure_ascii=False, indent=2)
        + "\n```\n",
        encoding="utf-8",
    )
    print("Исторический импорт завершён; отчёт сохранён в analysis")


if __name__ == "__main__":
    main()
