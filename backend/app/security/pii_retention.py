"""Remove closed leads' ciphertext after twelve calendar months, without PII logs."""

import calendar
import json
import sys
import threading
from datetime import UTC, datetime

from sqlalchemy import Engine, update

from app.models import Lead


def retention_cutoff(now: datetime) -> datetime:
    normalized = now.replace(tzinfo=UTC) if now.tzinfo is None else now.astimezone(UTC)
    year = normalized.year - 1
    day = min(normalized.day, calendar.monthrange(year, normalized.month)[1])
    return normalized.replace(year=year, day=day)


def purge_expired_lead_pii(engine: Engine, now: datetime | None = None) -> int:
    cutoff = retention_cutoff(now or datetime.now(UTC))
    with engine.begin() as connection:
        result = connection.execute(
            update(Lead)
            .where(
                Lead.status.in_(("done", "cancelled")),
                Lead.closed_at < cutoff,
                Lead.encrypted_pii.is_not(None),
            )
            .values(encrypted_pii=None)
        )
        return result.rowcount


class RetentionWorker:
    """One application-owned worker; immediate run, daily retry, interruptible stop."""

    def __init__(self, engine: Engine):
        self.engine = engine
        self.stop_event = threading.Event()
        self.thread = threading.Thread(
            target=self.run, name="pii-retention", daemon=True
        )

    def start(self) -> None:
        self.thread.start()

    def stop(self) -> None:
        self.stop_event.set()
        self.thread.join()

    def run(self) -> None:
        while not self.stop_event.is_set():
            try:
                erased = purge_expired_lead_pii(self.engine)
                print(
                    json.dumps({"event": "pii_retention_completed", "erased": erased}),
                    file=sys.stderr,
                )
            except Exception as error:
                # Exception messages can contain SQL parameters and ciphertext.
                print(
                    json.dumps(
                        {
                            "event": "pii_retention_failed",
                            "error_type": type(error).__name__,
                        }
                    ),
                    file=sys.stderr,
                )
            if self.stop_event.wait(24 * 60 * 60):
                return
