import json
import os
import sys
import threading
import time
from datetime import datetime, timedelta
from datetime import time as datetime_time
from typing import Literal
from zoneinfo import ZoneInfo

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.ads.agent import create_upload_reminders, run_ads_weekly
from app.ads.config import load_ads_config
from app.ads.importer import import_ads_file
from app.auto_contract_packages import DocumentGenerator
from app.models import SchedulerJobRun
from app.reports.daily import (
    reports_configured,
    send_daily_report,
    successful_auto_exists,
)
from app.tg_poller import send_message

MOSCOW_TZ = ZoneInfo("Europe/Moscow")
CHECK_HOURS = (9, 10, 11, 12, 13)
CHECK_MINUTE = 10
_scheduler_started = False


def _claim_job(
    engine: Engine,
    run_key: str,
    job_name: str,
    scheduled_for: datetime,
    *,
    retry_failed: bool = False,
) -> bool:
    with Session(engine) as session:
        existing = session.scalar(
            select(SchedulerJobRun).where(SchedulerJobRun.run_key == run_key)
        )
        if existing is not None:
            if not retry_failed or existing.status != "failed":
                return False
            existing.status = "running"
            existing.started_at = scheduled_for
            existing.finished_at = None
            existing.error_type = None
        else:
            session.add(
                SchedulerJobRun(
                    run_key=run_key,
                    job_name=job_name,
                    scheduled_for=scheduled_for,
                    status="running",
                    started_at=scheduled_for,
                )
            )
        session.commit()
    return True


def _finish_job(
    engine: Engine,
    run_key: str,
    status: Literal["ok", "failed"],
    finished_at: datetime,
    error: Exception | None = None,
) -> None:
    with Session(engine) as session:
        row = session.scalar(
            select(SchedulerJobRun).where(SchedulerJobRun.run_key == run_key)
        )
        if row is None:
            return
        row.status = status
        row.finished_at = finished_at
        row.error_type = type(error).__name__ if error is not None else None
        session.commit()


def run_due_ads_jobs(engine: Engine, now: datetime) -> tuple[str, ...]:
    local = now.astimezone(MOSCOW_TZ)
    if local.weekday() != 0 or local.hour != 9 or local.minute not in {15, 20, 30}:
        return ()
    job = {15: "import", 20: "reminders", 30: "weekly"}[local.minute]
    job_name = f"ads_{job}"
    run_key = f"{local.date().isoformat()}:{job_name}"
    if not _claim_job(engine, run_key, job_name, local):
        return ()
    try:
        config = load_ads_config()
        if job == "import":
            with Session(engine) as session:
                for platform, settings in config.platforms.items():
                    if settings.mode == "disabled":
                        continue
                    folder = config.root / platform
                    for path in sorted(folder.glob("*")):
                        if path.suffix.lower() in {".csv", ".xlsx", ".xls"}:
                            try:
                                import_ads_file(session, platform, path, now=local)
                                session.commit()
                            except Exception as error:
                                session.commit()
                                _warning("ads_import_failed", error)
                                token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
                                owner = os.getenv("OWNER_TG_ID", "").strip()
                                if token and owner.isdigit():
                                    send_message(
                                        token,
                                        int(owner),
                                        f"Ошибка импорта рекламы {platform}: "
                                        f"{type(error).__name__}; данные файла скрыты",
                                    )
        elif job == "reminders":
            with Session(engine) as session:
                reminders = create_upload_reminders(session, config, local)
                session.commit()
                reminder_payloads = [dict(row.payload) for row in reminders]
            token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
            owner = os.getenv("OWNER_TG_ID", "").strip()
            if reminder_payloads and token and owner.isdigit():
                for payload in reminder_payloads:
                    instructions = payload.get("instructions", [])
                    if not isinstance(instructions, list):
                        instructions = []
                    instruction_lines = "\n".join(
                        f"• {item}" for item in instructions if isinstance(item, str)
                    )
                    send_message(
                        token,
                        int(owner),
                        "Пора обновить рекламную выгрузку\n"
                        f"Площадка: {payload.get('platform')}\n"
                        f"Папка: {payload.get('folder')}\n"
                        f"{instruction_lines}",
                    )
        else:
            token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
            owner = os.getenv("OWNER_TG_ID", "").strip()

            def owner_sender(message: str) -> bool:
                return bool(
                    token
                    and owner.isdigit()
                    and send_message(token, int(owner), message)
                )

            result = run_ads_weekly(engine, local, owner_sender)
            if not result.get("delivered"):
                raise RuntimeError("weekly delivery failed")
    except Exception as error:
        _finish_job(engine, run_key, "failed", local, error)
        _warning("ads_scheduler_job_failed", error)
        return ()
    _finish_job(engine, run_key, "ok", local)
    return (job,)


def within_catchup_window(now: datetime) -> bool:
    local = now.astimezone(MOSCOW_TZ)
    start = datetime_time(9, CHECK_MINUTE)
    end = datetime_time(13, CHECK_MINUTE)
    return start <= local.time().replace(tzinfo=None) < end


def next_check_at(now: datetime) -> datetime:
    local = now.astimezone(MOSCOW_TZ)
    for hour in CHECK_HOURS:
        candidate = local.replace(
            hour=hour, minute=CHECK_MINUTE, second=0, microsecond=0
        )
        if candidate > local:
            return candidate
    tomorrow = local.date() + timedelta(days=1)
    return datetime.combine(tomorrow, datetime_time(9, CHECK_MINUTE), tzinfo=MOSCOW_TZ)


def run_due_auto(
    engine: Engine,
    now: datetime,
    auto_package_generator: DocumentGenerator | None = None,
) -> bool:
    if not within_catchup_window(now):
        return False
    local = now.astimezone(MOSCOW_TZ)
    with Session(engine) as session:
        if successful_auto_exists(session, now.astimezone(MOSCOW_TZ).date()):
            return False
    run_key = f"{local.date().isoformat()}:daily_auto"
    if not _claim_job(engine, run_key, "daily_auto", local, retry_failed=True):
        return False
    try:
        if auto_package_generator is None:
            send_daily_report(engine, "auto", now)
        else:
            send_daily_report(
                engine,
                "auto",
                now,
                auto_package_generator=auto_package_generator,
            )
    except Exception as error:
        _finish_job(engine, run_key, "failed", local, error)
        raise
    _finish_job(engine, run_key, "ok", local)
    return True


def _warning(event: str, error: Exception | None = None) -> None:
    payload = {"level": "warning", "event": event}
    if error is not None:
        payload["error_type"] = type(error).__name__
    print(json.dumps(payload), file=sys.stderr)


def _scheduler_loop(
    engine: Engine, auto_package_generator: DocumentGenerator | None = None
) -> None:
    while True:
        now = datetime.now(MOSCOW_TZ)
        run_scheduler_iteration(engine, now, auto_package_generator)
        time.sleep(poll_delay_seconds(now))


def run_scheduler_iteration(
    engine: Engine,
    now: datetime,
    auto_package_generator: DocumentGenerator | None = None,
) -> None:
    try:
        run_due_gnom_job(engine, now)
    except Exception as error:
        _warning("gnom_scheduler_attempt_failed", error)
    try:
        run_due_auto(engine, now, auto_package_generator)
    except Exception as error:
        _warning("daily_report_job_failed", error)
    try:
        run_due_ads_jobs(engine, now)
    except Exception as error:
        _warning("ads_scheduler_job_failed", error)


def poll_delay_seconds(now: datetime) -> float:
    target = next_check_at(now)
    return min(60.0, max(1.0, (target - datetime.now(MOSCOW_TZ)).total_seconds()))


def run_due_gnom_job(engine: Engine, now: datetime) -> bool:
    from app.gnom_scheduler import run_gnom_weekly
    from app.models import GnomWeeklyRun

    local = now.astimezone(MOSCOW_TZ)
    if local.weekday() != 0 or (local.hour, local.minute) < (9, 10):
        return False
    run_key = f"{local.date().isoformat()}:gnom_weekly"
    if not _claim_job(engine, run_key, "gnom_weekly", local, retry_failed=True):
        return False
    try:
        delivered = run_gnom_weekly(engine, local)
        with Session(engine) as session:
            weekly = session.get(GnomWeeklyRun, local.date())
            failed = weekly is not None and weekly.status == "failed"
        if failed:
            error = RuntimeError("gnom weekly delivery failed")
            _finish_job(engine, run_key, "failed", local, error)
            return False
    except Exception as error:
        _finish_job(engine, run_key, "failed", local, error)
        raise
    _finish_job(engine, run_key, "ok", local)
    return delivered


_run_scheduler_iteration = run_scheduler_iteration


def start_report_scheduler(
    engine: Engine, auto_package_generator: DocumentGenerator | None = None
) -> None:
    global _scheduler_started

    if _scheduler_started:
        return
    if not reports_configured():
        _warning("reports_scheduler_degraded")
    thread = threading.Thread(
        target=_scheduler_loop,
        args=(engine, auto_package_generator),
        daemon=True,
    )
    thread.start()
    _scheduler_started = True


def reports_status() -> Literal["ok", "degraded"]:
    return "ok" if _scheduler_started and reports_configured() else "degraded"
