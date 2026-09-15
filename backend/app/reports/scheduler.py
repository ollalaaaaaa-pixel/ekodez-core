import json
import os
import sys
import threading
import time
from datetime import datetime, timedelta
from datetime import time as datetime_time
from typing import Literal
from zoneinfo import ZoneInfo

from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.ads.agent import create_upload_reminders, run_ads_weekly
from app.ads.config import AdsConfigError, load_ads_config
from app.ads.importer import import_ads_file
from app.auto_contract_packages import DocumentGenerator
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
_ads_job_runs: set[str] = set()


def run_due_ads_jobs(engine: Engine, now: datetime) -> tuple[str, ...]:
    local = now.astimezone(MOSCOW_TZ)
    if local.weekday() != 0 or local.hour != 9 or local.minute not in {15, 20, 30}:
        return ()
    job = {15: "import", 20: "reminders", 30: "weekly"}[local.minute]
    run_key = f"{local.date().isoformat()}:{job}"
    if run_key in _ads_job_runs:
        return ()
    try:
        config = load_ads_config()
    except AdsConfigError:
        _warning("ads_scheduler_degraded")
        return ()
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
                                    f"Ошибка импорта рекламы {platform}: {path.name}; "
                                    f"{str(error)[:160]}",
                                )
    elif job == "reminders":
        with Session(engine) as session:
            reminders = create_upload_reminders(session, config, local)
            session.commit()
        if reminders:
            token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
            owner = os.getenv("OWNER_TG_ID", "").strip()
            if token and owner.isdigit():
                for row in reminders:
                    instructions = row.payload.get("instructions", [])
                    if not isinstance(instructions, list):
                        instructions = []
                    instruction_lines = "\n".join(
                        f"• {item}" for item in instructions if isinstance(item, str)
                    )
                    send_message(
                        token,
                        int(owner),
                        "Пора обновить рекламную выгрузку\n"
                        f"Площадка: {row.payload.get('platform')}\n"
                        f"Папка: {row.payload.get('folder')}\n"
                        f"{instruction_lines}",
                    )
    else:
        token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
        owner = os.getenv("OWNER_TG_ID", "").strip()

        def owner_sender(message: str) -> bool:
            return bool(
                token and owner.isdigit() and send_message(token, int(owner), message)
            )

        run_ads_weekly(engine, local, owner_sender)
    _ads_job_runs.add(run_key)
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
    with Session(engine) as session:
        if successful_auto_exists(session, now.astimezone(MOSCOW_TZ).date()):
            return False
    if auto_package_generator is None:
        send_daily_report(engine, "auto", now)
    else:
        send_daily_report(
            engine,
            "auto",
            now,
            auto_package_generator=auto_package_generator,
        )
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
        try:
            run_due_auto(engine, now, auto_package_generator)
            run_due_ads_jobs(engine, now)
        except Exception as error:
            _warning("reports_scheduler_attempt_failed", error)
        target = next_check_at(now)
        delay = min(60.0, max(1.0, (target - datetime.now(MOSCOW_TZ)).total_seconds()))
        time.sleep(delay)


def start_report_scheduler(
    engine: Engine, auto_package_generator: DocumentGenerator | None = None
) -> None:
    global _scheduler_started

    if _scheduler_started:
        return
    if not reports_configured():
        _scheduler_started = False
        _warning("reports_scheduler_degraded")
        return
    thread = threading.Thread(
        target=_scheduler_loop,
        args=(engine, auto_package_generator),
        daemon=True,
    )
    thread.start()
    _scheduler_started = True


def reports_status() -> Literal["ok", "degraded"]:
    return "ok" if _scheduler_started and reports_configured() else "degraded"
