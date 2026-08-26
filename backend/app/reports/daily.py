import math
import os
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Literal
from zoneinfo import ZoneInfo

from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from app.inventory import LOW_STOCK_RATIO
from app.models import Inventory, Lead, Object, SentReport, Transaction
from app.tg_poller import send_message

MONEY_QUANTUM = Decimal("0.01")
DETAIL_LIMIT = 10
DETAIL_LABEL_LIMIT = 120
MANUAL_COOLDOWN_SECONDS = 60
MOSCOW_TZ = ZoneInfo("Europe/Moscow")
RecipientSender = Callable[[str, int, str], bool]
ReportType = Literal["auto", "manual"]
_delivery_lock = threading.Lock()


class ReportsConfigurationError(RuntimeError):
    pass


class TelegramDeliveryError(RuntimeError):
    pass


class ManualReportCooldown(RuntimeError):
    def __init__(self, retry_after_seconds: int):
        self.retry_after_seconds = retry_after_seconds
        super().__init__("manual daily report is on cooldown")


@dataclass(frozen=True)
class OverdueObject:
    name: str
    next_treatment_date: date


@dataclass(frozen=True)
class LowStockItem:
    chemical_name: str
    quantity: Decimal
    unit: str


@dataclass(frozen=True)
class ReportSnapshot:
    report_date: date
    revenue: Decimal
    expenses: Decimal
    profit: Decimal
    margin_pct: Decimal
    new_leads: int
    closed_leads: int
    disputed_operations: int
    overdue_objects: tuple[OverdueObject, ...]
    low_stock_items: tuple[LowStockItem, ...]


def _money(value: Decimal | int | None) -> Decimal:
    return Decimal(value or 0).quantize(MONEY_QUANTUM, rounding=ROUND_HALF_UP)


def _datetime_bounds(report_date: date) -> tuple[datetime, datetime]:
    local_start = datetime.combine(report_date, time.min, tzinfo=MOSCOW_TZ)
    utc_start = local_start.astimezone(UTC)
    return utc_start, utc_start + timedelta(days=1)


def build_daily_snapshot(session: Session, report_date: date) -> ReportSnapshot:
    confirmed = Transaction.review_required.is_(False)
    revenue = _money(
        session.scalar(
            select(func.sum(Transaction.amount)).where(
                Transaction.operation_date == report_date,
                Transaction.kind == "income",
                confirmed,
            )
        )
    )
    expenses = _money(
        session.scalar(
            select(func.sum(Transaction.amount)).where(
                Transaction.operation_date == report_date,
                Transaction.kind == "expense",
                confirmed,
            )
        )
    )
    profit = _money(revenue - expenses)
    margin_pct = (
        _money((profit / revenue) * Decimal("100"))
        if revenue != Decimal("0.00")
        else Decimal("0.00")
    )
    start, end = _datetime_bounds(report_date)
    new_leads = int(
        session.scalar(
            select(func.count(Lead.id)).where(
                Lead.created_at >= start, Lead.created_at < end
            )
        )
        or 0
    )
    closed_leads = int(
        session.scalar(
            select(func.count(Lead.id)).where(
                Lead.closed_at.is_not(None),
                Lead.closed_at >= start,
                Lead.closed_at < end,
            )
        )
        or 0
    )
    disputed_operations = int(
        session.scalar(
            select(func.count(Transaction.id)).where(
                Transaction.operation_date == report_date,
                Transaction.needs_review.is_(True),
            )
        )
        or 0
    )

    current_date = report_date + timedelta(days=1)
    overdue_rows = session.scalars(
        select(Object)
        .where(
            Object.next_treatment_date.is_not(None),
            Object.next_treatment_date < current_date,
            Object.status != "inactive",
        )
        .order_by(Object.next_treatment_date, Object.id)
    ).all()
    overdue_objects = tuple(
        OverdueObject(
            name=(f"Объект #{row.id}" if row.type == "apartment" else row.name),
            next_treatment_date=row.next_treatment_date,
        )
        for row in overdue_rows
        if row.next_treatment_date is not None
    )

    inventory_rows = session.scalars(
        select(Inventory).order_by(Inventory.chemical_name, Inventory.id)
    ).all()
    low_stock_items = tuple(
        LowStockItem(
            chemical_name=row.chemical_name,
            quantity=Decimal(row.quantity),
            unit=row.unit,
        )
        for row in inventory_rows
        if Decimal(row.quantity) < Decimal(row.initial_quantity) * LOW_STOCK_RATIO
    )

    return ReportSnapshot(
        report_date=report_date,
        revenue=revenue,
        expenses=expenses,
        profit=profit,
        margin_pct=margin_pct,
        new_leads=new_leads,
        closed_leads=closed_leads,
        disputed_operations=disputed_operations,
        overdue_objects=overdue_objects,
        low_stock_items=low_stock_items,
    )


def _format_money(value: Decimal) -> str:
    return f"{value:,.2f}".replace(",", " ")


def _append_truncated(lines: list[str], details: list[str], total: int) -> None:
    lines.extend(details[:DETAIL_LIMIT])
    remaining = total - DETAIL_LIMIT
    if remaining > 0:
        lines.append(f"… и ещё {remaining}")


def _truncate_label(value: str) -> str:
    if len(value) <= DETAIL_LABEL_LIMIT:
        return value
    return value[: DETAIL_LABEL_LIMIT - 1] + "…"


def format_daily_report(snapshot: ReportSnapshot) -> str:
    lines = [
        f"Сводка ЭКОДЕЗ за {snapshot.report_date:%d.%m.%Y}",
        "",
        "Финансы",
        f"Доход: {_format_money(snapshot.revenue)} ₽",
        f"Расход: {_format_money(snapshot.expenses)} ₽",
        f"Прибыль: {_format_money(snapshot.profit)} ₽",
        f"Маржа: {snapshot.margin_pct:.2f}%",
        "",
        "Заявки",
        f"Новые: {snapshot.new_leads}",
        f"Закрытые: {snapshot.closed_leads}",
        "",
        "Контроль",
        f"Спорные операции: {snapshot.disputed_operations}",
        f"Просроченные обработки: {len(snapshot.overdue_objects)}",
    ]
    _append_truncated(
        lines,
        [
            f"• {_truncate_label(row.name)} — {row.next_treatment_date:%d.%m.%Y}"
            for row in snapshot.overdue_objects
        ],
        len(snapshot.overdue_objects),
    )
    lines.append(f"Низкие остатки: {len(snapshot.low_stock_items)}")
    _append_truncated(
        lines,
        [
            f"• {_truncate_label(row.chemical_name)} — "
            f"{format(row.quantity.normalize(), 'f')} {row.unit}"
            for row in snapshot.low_stock_items
        ],
        len(snapshot.low_stock_items),
    )
    return "\n".join(lines)


def reports_configured() -> bool:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    owner_id = os.getenv("OWNER_TG_ID", "").strip()
    if not token or not owner_id:
        return False
    try:
        int(owner_id)
    except ValueError:
        return False
    return True


def _owner_recipient() -> tuple[str, int]:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    owner_id = os.getenv("OWNER_TG_ID", "").strip()
    if not token or not owner_id:
        raise ReportsConfigurationError("daily reports are not configured")
    try:
        chat_id = int(owner_id)
    except ValueError as error:
        raise ReportsConfigurationError("daily reports are not configured") from error
    return token, chat_id


def successful_auto_exists(
    session: Session, report_date: date, recipient_key: str = "owner"
) -> bool:
    return (
        session.scalar(
            select(SentReport.id).where(
                SentReport.report_date == report_date,
                SentReport.report_type == "auto",
                SentReport.recipient_key == recipient_key,
                SentReport.status == "sent",
            )
        )
        is not None
    )


def _normalize_stored_datetime(value: datetime, reference: datetime) -> datetime:
    if value.tzinfo is None and reference.tzinfo is not None:
        return value.replace(tzinfo=reference.tzinfo)
    return value


def _detached(session: Session, row: SentReport) -> SentReport:
    session.refresh(row)
    session.expunge(row)
    return row


def _send_daily_report_locked(
    engine: Engine,
    report_type: ReportType,
    now: datetime,
    sender: RecipientSender = send_message,
) -> SentReport:
    if report_type not in ("auto", "manual"):
        raise ValueError("unsupported report type")
    token, chat_id = _owner_recipient()
    recipient_key = "owner"
    send_date = now.date()

    with Session(engine) as session:
        if report_type == "auto":
            existing = session.scalar(
                select(SentReport).where(
                    SentReport.report_date == send_date,
                    SentReport.report_type == "auto",
                    SentReport.recipient_key == recipient_key,
                    SentReport.status == "sent",
                )
            )
            if existing is not None:
                return _detached(session, existing)
        else:
            latest = session.scalar(
                select(SentReport)
                .where(
                    SentReport.report_type == "manual",
                    SentReport.recipient_key == recipient_key,
                    SentReport.status == "sent",
                )
                .order_by(SentReport.sent_at.desc(), SentReport.id.desc())
                .limit(1)
            )
            if latest is not None:
                latest_at = _normalize_stored_datetime(latest.sent_at, now)
                elapsed = (now - latest_at).total_seconds()
                if elapsed < MANUAL_COOLDOWN_SECONDS:
                    remaining = math.ceil(MANUAL_COOLDOWN_SECONDS - elapsed)
                    raise ManualReportCooldown(max(1, remaining))

        snapshot = build_daily_snapshot(session, send_date - timedelta(days=1))
        message = format_daily_report(snapshot)
        try:
            delivered = sender(token, chat_id, message)
        except Exception:
            delivered = False
        row = SentReport(
            report_date=send_date,
            report_type=report_type,
            recipient_key=recipient_key,
            status="sent" if delivered else "failed",
            sent_at=now,
        )
        session.add(row)
        session.commit()
        result = _detached(session, row)

    if not delivered:
        raise TelegramDeliveryError("Telegram delivery failed")
    return result


def send_daily_report(
    engine: Engine,
    report_type: ReportType,
    now: datetime,
    sender: RecipientSender = send_message,
) -> SentReport:
    # В утверждённом локальном deployment один backend-процесс. Блокировка
    # сериализует HTTP-запросы и scheduler для auto-idempotency и cooldown.
    with _delivery_lock:
        return _send_daily_report_locked(engine, report_type, now, sender)
