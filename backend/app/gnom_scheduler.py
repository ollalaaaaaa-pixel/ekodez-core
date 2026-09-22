"""Monday 09:10 transition job; explicitly enabled by the owner."""

import hashlib
import os
from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy import Engine, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.gnom_parser import GnomError
from app.gnom_service import analytics, import_file
from app.models import GnomImportRun, GnomSettings, GnomWeeklyAttempt, GnomWeeklyRun

IMPORT_ROOT = Path(r"C:\D\Экодез\import\gnom")
RUN_LEASE = timedelta(minutes=90)


def owner_alert(message: str) -> bool:
    from app.tg_poller import send_message

    token, owner = os.getenv("TELEGRAM_BOT_TOKEN", ""), os.getenv("OWNER_TG_ID", "")
    if not token or not owner.isdigit():
        return False
    return send_message(token, int(owner), message)


def run_gnom_weekly(
    engine: Engine,
    now: datetime,
    sender: Callable[[str], bool] = owner_alert,
    root: Path | None = None,
    *,
    scheduled_for: datetime | None = None,
) -> bool:
    local = now.astimezone(ZoneInfo("Europe/Moscow"))
    slot = (scheduled_for or now).astimezone(ZoneInfo("Europe/Moscow"))
    if slot > local or slot.weekday() != 0 or (slot.hour, slot.minute) < (9, 10):
        return False
    root = root or IMPORT_ROOT
    week = slot.date()
    started_at = local.replace(tzinfo=None)
    with Session(engine) as session:
        if engine.dialect.name == "sqlite":
            session.execute(text("BEGIN IMMEDIATE"))
        settings = session.get(GnomSettings, 1)
        if not settings or not settings.weekly_enabled:
            return False
        existing = session.get(GnomWeeklyRun, week)
        if existing and existing.status == "sent":
            return False
        if (
            existing
            and existing.status == "running"
            and existing.started_at >= started_at - RUN_LEASE
        ):
            return False
        if existing and existing.status == "running":
            existing.status = "stale_failed"
            previous = session.scalar(
                select(GnomWeeklyAttempt)
                .where(
                    GnomWeeklyAttempt.week == week,
                    GnomWeeklyAttempt.status == "running",
                )
                .order_by(GnomWeeklyAttempt.id.desc())
            )
            if previous is None:
                previous = GnomWeeklyAttempt(
                    week=week, status="stale_failed", started_at=existing.started_at
                )
                session.add(previous)
            previous.status = "stale_failed"
            previous.finished_at = started_at
            previous.error_type = "LeaseExpired"
        if existing:
            existing.status = "running"
            existing.started_at = started_at
        else:
            session.add(
                GnomWeeklyRun(week=week, status="running", started_at=started_at)
            )
        session.flush()
        attempt = GnomWeeklyAttempt(week=week, status="running", started_at=started_at)
        session.add(attempt)
        try:
            session.flush()
            attempt_id = attempt.id
            session.commit()
        except IntegrityError:
            session.rollback()
            return False
    imported = failed = 0
    delivered = False
    try:
        for path in sorted(root.iterdir()) if root.is_dir() else []:
            if (
                not path.is_file()
                or path.is_symlink()
                or path.suffix.lower() not in {".xlsx", ".csv", ".xls"}
            ):
                continue
            if not path.resolve().is_relative_to(root.resolve()):
                continue
            with path.open("rb") as stream:
                content = stream.read(20 * 1024 * 1024 + 1)
            digest = hashlib.sha256(content).hexdigest()
            with Session(engine) as session:
                if session.scalar(
                    select(GnomImportRun.id).where(
                        GnomImportRun.file_hash == digest,
                        GnomImportRun.status == "success",
                    )
                ):
                    continue
            try:
                import_file(engine, content, path.name, authorized=True)
                imported += 1
            except GnomError:
                failed += 1
        with Session(engine) as session:
            report = analytics(session)
        message = (
            f"Гном: импортировано файлов {imported}, ошибок {failed}.\n"
            "Напоминание: выгрузите актуальную историю в папку import/gnom.\n"
            "Недельная аналитика истории: средний чек "
            f"{report['average_check'] or 'нет данных'}; "
            f"Created→Start, часов: {report['lead_time_hours'] or 'нет данных'}; "
            f"переносов: {report['rescheduled']}.\n"
            "Сезонность, выручка по месяцам: " + str(report["revenue_by_month"])
        )
        delivered = sender(message[:4000])
    finally:
        with Session(engine) as session, session.begin():
            run = session.get(GnomWeeklyRun, week)
            assert run is not None
            finished_attempt = session.get(GnomWeeklyAttempt, attempt_id)
            assert finished_attempt is not None
            if finished_attempt.status == "running":
                finished_attempt.status = "sent" if delivered else "failed"
                finished_attempt.finished_at = datetime.now(
                    ZoneInfo("Europe/Moscow")
                ).replace(tzinfo=None)
                if run.started_at == started_at:
                    run.status = finished_attempt.status
    return delivered
