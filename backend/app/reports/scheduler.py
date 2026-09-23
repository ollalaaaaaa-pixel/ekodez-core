import json
import os
import sys
import threading
from datetime import datetime, timedelta
from datetime import time as datetime_time
from typing import Literal
from zoneinfo import ZoneInfo

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.ads.agent import create_upload_reminders, run_ads_weekly
from app.ads.config import AdsConfigError, load_ads_config
from app.ads.importer import import_ads_file
from app.auto_contract_packages import DocumentGenerator
from app.background_workers import ThreadWorker, WorkerRegistry
from app.models import SchedulerJobRun, SchedulerState
from app.reports.daily import (
    reports_configured,
    send_daily_report,
    successful_auto_exists,
)
from app.tg_poller import send_message

MOSCOW_TZ = ZoneInfo("Europe/Moscow")
CHECK_HOURS = (9, 10, 11, 12, 13)
CHECK_MINUTE = 10
_scheduler_worker: ThreadWorker | None = None


def _claim_job(
    engine: Engine,
    run_key: str,
    job_name: str,
    scheduled_for: datetime,
    *,
    retry_failed: bool = False,
    started_at: datetime | None = None,
    blocked_start: bool = False,
) -> str | None:
    current = (started_at or scheduled_for).astimezone(MOSCOW_TZ).replace(tzinfo=None)
    with Session(engine) as session:
        existing = session.scalar(
            select(SchedulerJobRun)
            .where(
                SchedulerJobRun.job_name == job_name,
                (SchedulerJobRun.run_key == run_key)
                | SchedulerJobRun.run_key.like(f"{run_key}:retry:%"),
            )
            .order_by(SchedulerJobRun.id.desc())
        )
        if existing is not None:
            if existing.status == "running":
                try:
                    timeout = load_ads_config().scheduler_stale_timeout_minutes
                except AdsConfigError:
                    timeout = 30
                if existing.started_at >= current - timedelta(minutes=timeout):
                    return None
                existing.status = "stale_failed"
                existing.finished_at = current
                existing.error_type = "LeaseExpired"
            elif existing.status != "stale_failed" and not (
                retry_failed and existing.status == "failed"
            ):
                return None
            run_key = f"{run_key}:retry:{existing.id + 1}"
        if blocked_start:
            session.commit()
            return None
        session.add(
            SchedulerJobRun(
                run_key=run_key,
                job_name=job_name,
                scheduled_for=scheduled_for,
                status="running",
                started_at=current,
            )
        )
        session.commit()
    return run_key


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
        if row.status != "running":
            return
        row.status = status
        row.finished_at = finished_at.astimezone(MOSCOW_TZ).replace(tzinfo=None)
        row.error_type = type(error).__name__ if error is not None else None
        session.commit()


def _due_times(
    last_iteration_time: datetime, now: datetime, *, minutes: tuple[int, ...]
) -> list[datetime]:
    last = last_iteration_time.astimezone(MOSCOW_TZ)
    local = now.astimezone(MOSCOW_TZ)
    due: list[datetime] = []
    day = last.date()
    while day <= local.date():
        if day.weekday() == 0:
            for minute in minutes:
                scheduled = datetime.combine(
                    day, datetime_time(9, minute), tzinfo=MOSCOW_TZ
                )
                if last < scheduled <= local:
                    due.append(scheduled)
        day += timedelta(days=1)
    return due


def run_due_ads_jobs(
    engine: Engine, now: datetime, last_iteration_time: datetime | None = None
) -> tuple[str, ...]:
    last = last_iteration_time or now - timedelta(minutes=1)
    completed: list[str] = []
    due = set(_due_times(last, now, minutes=(15, 20, 30)))
    local = now.astimezone(MOSCOW_TZ)
    midnight = local.replace(hour=0, minute=0, second=0, microsecond=0)
    with Session(engine) as session:
        unfinished = session.scalars(
            select(SchedulerJobRun.scheduled_for).where(
                SchedulerJobRun.job_name.in_(
                    ("ads_import", "ads_reminders", "ads_weekly")
                ),
                SchedulerJobRun.status.in_(("running", "stale_failed")),
                SchedulerJobRun.scheduled_for >= midnight.replace(tzinfo=None),
                SchedulerJobRun.scheduled_for <= local.replace(tzinfo=None),
            )
        ).all()
    due.update(value.replace(tzinfo=MOSCOW_TZ) for value in unfinished)
    for scheduled in sorted(due):
        completed.extend(_run_ads_job(engine, scheduled, now))
    return tuple(completed)


def _run_ads_job(
    engine: Engine, scheduled_for: datetime, now: datetime
) -> tuple[str, ...]:
    local = now.astimezone(MOSCOW_TZ)
    job = {15: "import", 20: "reminders", 30: "weekly"}[scheduled_for.minute]
    job_name = f"ads_{job}"
    base_key = f"{scheduled_for.date().isoformat()}:{job_name}"
    run_key = _claim_job(engine, base_key, job_name, scheduled_for, started_at=local)
    if run_key is None:
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

            result = run_ads_weekly(engine, scheduled_for, owner_sender)
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
    claimed_key = _claim_job(engine, run_key, "daily_auto", local, retry_failed=True)
    if claimed_key is None:
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
        _finish_job(engine, claimed_key, "failed", local, error)
        raise
    _finish_job(engine, claimed_key, "ok", local)
    return True


def _warning(event: str, error: Exception | None = None) -> None:
    payload = {"level": "warning", "event": event}
    if error is not None:
        payload["error_type"] = type(error).__name__
    print(json.dumps(payload), file=sys.stderr)


def _scheduler_loop(
    engine: Engine,
    auto_package_generator: DocumentGenerator | None = None,
    stop_event: threading.Event | None = None,
) -> None:
    stop = stop_event if stop_event is not None else threading.Event()
    while not stop.is_set():
        now = datetime.now(MOSCOW_TZ)
        try:
            run_scheduler_iteration(engine, now, auto_package_generator)
        except Exception as error:
            if not stop.is_set():
                _warning("scheduler_iteration_failed", error)
        if stop.wait(poll_delay_seconds(now)):
            break


def _last_iteration(engine: Engine, now: datetime) -> datetime:
    with Session(engine) as session:
        row = session.get(SchedulerState, "core")
    if row is None:
        return now.astimezone(MOSCOW_TZ).replace(
            hour=0, minute=0, second=0, microsecond=0
        ) - timedelta(microseconds=1)
    return row.last_iteration_time.replace(tzinfo=MOSCOW_TZ)


def _record_iteration(engine: Engine, now: datetime) -> None:
    local = now.astimezone(MOSCOW_TZ).replace(tzinfo=None)
    with Session(engine) as session:
        row = session.get(SchedulerState, "core")
        if row is None:
            session.add(SchedulerState(name="core", last_iteration_time=local))
        elif row.last_iteration_time < local:
            row.last_iteration_time = local
        session.commit()


def run_scheduler_iteration(
    engine: Engine,
    now: datetime,
    auto_package_generator: DocumentGenerator | None = None,
) -> None:
    last_iteration_time = _last_iteration(engine, now)
    try:
        run_due_gnom_job(engine, now, last_iteration_time)
    except Exception as error:
        _warning("gnom_scheduler_attempt_failed", error)
    try:
        run_due_auto(engine, now, auto_package_generator)
    except Exception as error:
        _warning("daily_report_job_failed", error)
    try:
        run_due_ads_jobs(engine, now, last_iteration_time)
    except Exception as error:
        _warning("ads_scheduler_job_failed", error)
    _record_iteration(engine, now)


def poll_delay_seconds(now: datetime) -> float:
    target = next_check_at(now)
    return min(60.0, max(1.0, (target - datetime.now(MOSCOW_TZ)).total_seconds()))


def run_due_gnom_job(
    engine: Engine, now: datetime, last_iteration_time: datetime | None = None
) -> bool:
    from app.models import GnomSettings

    local = now.astimezone(MOSCOW_TZ)
    last = last_iteration_time or local - timedelta(minutes=1)
    with Session(engine) as session:
        settings = session.get(GnomSettings, 1)
        if settings is None or not settings.weekly_enabled:
            return False
        pending = session.scalars(
            select(SchedulerJobRun.scheduled_for).where(
                SchedulerJobRun.job_name == "gnom_weekly",
                SchedulerJobRun.scheduled_for <= local.replace(tzinfo=None),
                SchedulerJobRun.status.in_(("running", "failed", "stale_failed")),
            )
        ).all()
    due = set(_due_times(last, local, minutes=(10,)))
    due.update(value.replace(tzinfo=MOSCOW_TZ) for value in pending)
    delivered = False
    for scheduled in sorted(due):
        if scheduled.weekday() != 0 or (scheduled.hour, scheduled.minute) != (9, 10):
            continue
        try:
            delivered = _run_gnom_slot(engine, scheduled, local) or delivered
        except Exception as error:
            _warning("gnom_scheduler_attempt_failed", error)
    return delivered


def _run_gnom_slot(engine: Engine, scheduled: datetime, local: datetime) -> bool:
    from app.gnom_scheduler import RUN_LEASE, run_gnom_weekly
    from app.models import GnomWeeklyRun

    with Session(engine) as session:
        weekly = session.get(GnomWeeklyRun, scheduled.date())
        blocked = bool(
            weekly is not None
            and weekly.status == "running"
            and weekly.started_at >= local.replace(tzinfo=None) - RUN_LEASE
        )
    run_key = f"{scheduled.date().isoformat()}:gnom_weekly"
    claimed_key = _claim_job(
        engine,
        run_key,
        "gnom_weekly",
        scheduled,
        retry_failed=True,
        started_at=local,
        blocked_start=blocked,
    )
    if claimed_key is None:
        return False
    try:
        delivered = run_gnom_weekly(engine, local, scheduled_for=scheduled)
        with Session(engine) as session:
            weekly = session.get(GnomWeeklyRun, scheduled.date())
            completed = weekly is not None and weekly.status == "sent"
        if not completed:
            error = RuntimeError("gnom weekly handler did not complete")
            _finish_job(engine, claimed_key, "failed", local, error)
            return False
    except Exception as error:
        _finish_job(engine, claimed_key, "failed", local, error)
        raise
    _finish_job(engine, claimed_key, "ok", local)
    return delivered


_run_scheduler_iteration = run_scheduler_iteration


def start_report_scheduler(
    engine: Engine,
    auto_package_generator: DocumentGenerator | None = None,
    registry: WorkerRegistry | None = None,
) -> None:
    global _scheduler_worker

    if _scheduler_worker is not None and _scheduler_worker.thread.is_alive():
        if registry is not None:
            registry.register(_scheduler_worker)
        return
    if not reports_configured():
        _warning("reports_scheduler_degraded")
    _scheduler_worker = ThreadWorker(
        "ekodez-report-scheduler",
        lambda stop: _scheduler_loop(engine, auto_package_generator, stop),
    )
    if registry is None:
        _scheduler_worker.start()
    else:
        registry.start(_scheduler_worker)


def reports_status() -> Literal["ok", "degraded"]:
    alive = _scheduler_worker is not None and _scheduler_worker.thread.is_alive()
    return "ok" if alive and reports_configured() else "degraded"
