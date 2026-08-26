import json
import sys
import threading
import time
from datetime import datetime, timedelta
from datetime import time as datetime_time
from typing import Literal
from zoneinfo import ZoneInfo

from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.reports.daily import (
    reports_configured,
    send_daily_report,
    successful_auto_exists,
)

MOSCOW_TZ = ZoneInfo("Europe/Moscow")
CHECK_HOURS = (9, 10, 11, 12)
_scheduler_started = False


def within_catchup_window(now: datetime) -> bool:
    local = now.astimezone(MOSCOW_TZ)
    start = datetime_time(9, 0)
    end = datetime_time(13, 0)
    return start <= local.time().replace(tzinfo=None) < end


def next_check_at(now: datetime) -> datetime:
    local = now.astimezone(MOSCOW_TZ)
    for hour in CHECK_HOURS:
        candidate = local.replace(hour=hour, minute=0, second=0, microsecond=0)
        if candidate > local:
            return candidate
    tomorrow = local.date() + timedelta(days=1)
    return datetime.combine(tomorrow, datetime_time(9, 0), tzinfo=MOSCOW_TZ)


def run_due_auto(engine: Engine, now: datetime) -> bool:
    if not within_catchup_window(now):
        return False
    with Session(engine) as session:
        if successful_auto_exists(session, now.astimezone(MOSCOW_TZ).date()):
            return False
    send_daily_report(engine, "auto", now)
    return True


def _warning(event: str, error: Exception | None = None) -> None:
    payload = {"level": "warning", "event": event}
    if error is not None:
        payload["error_type"] = type(error).__name__
    print(json.dumps(payload), file=sys.stderr)


def _scheduler_loop(engine: Engine) -> None:
    while True:
        now = datetime.now(MOSCOW_TZ)
        try:
            run_due_auto(engine, now)
        except Exception as error:
            _warning("reports_scheduler_attempt_failed", error)
        target = next_check_at(now)
        delay = max(1.0, (target - datetime.now(MOSCOW_TZ)).total_seconds())
        time.sleep(delay)


def start_report_scheduler(engine: Engine) -> None:
    global _scheduler_started

    if _scheduler_started:
        return
    if not reports_configured():
        _scheduler_started = False
        _warning("reports_scheduler_degraded")
        return
    thread = threading.Thread(target=_scheduler_loop, args=(engine,), daemon=True)
    thread.start()
    _scheduler_started = True


def reports_status() -> Literal["ok", "degraded"]:
    return "ok" if _scheduler_started and reports_configured() else "degraded"
