"""Transactional historical import and masked, owner-supplied signals."""

import hashlib
import json
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from statistics import median

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.gnom_parser import (
    GnomError,
    GnomRow,
    canonical,
    normalized_address,
    parse_gnom,
    phones,
    private_hash,
    signature,
)
from app.models import (
    Client,
    GnomCandidate,
    GnomImportRun,
    GnomPlatformRule,
    GnomRecord,
    GnomSettings,
    Lead,
    Object,
    Transaction,
    TransactionCategory,
    Treatment,
)
from app.security.pii import decrypt_sensitive_mapping, encrypt_sensitive_mapping


def encrypted(values: dict[str, object]) -> str:
    result = encrypt_sensitive_mapping(values)
    if result is None:
        raise GnomError("Не настроен ключ PII")
    return result


def matching_history(
    session: Session, address: str, phone: str, before: datetime | None = None
) -> list[GnomRecord]:
    hashes = {private_hash("phone", number) for number in phones(phone)}
    address_hash = (
        private_hash("address", normalized_address(address)) if address.strip() else ""
    )
    query = select(GnomRecord).where(
        GnomRecord.finished.is_(True), GnomRecord.cancelled.is_(False)
    )
    if before:
        query = query.where(GnomRecord.start < before)
    return [
        row
        for row in session.scalars(
            query.order_by(GnomRecord.start.desc(), GnomRecord.id.desc())
        )
        if (address_hash and row.address_hash == address_hash)
        or hashes.intersection(row.phone_hashes)
    ]


def history_summary(
    session: Session, address: str, phone: str, before: datetime | None = None
) -> dict[str, object] | None:
    try:
        matches = matching_history(session, address, phone, before)
    except GnomError:
        return None
    if not matches:
        return None
    row = matches[0]
    settings = session.get(GnomSettings, 1)
    days = settings.warranty_days if settings else None
    return {
        "object_id": row.object_id,
        "last_treatment": row.start.isoformat(),
        "pests": row.signals.get("pests", []),
        "methods": row.signals.get("methods", []),
        "price": f"{row.income:.2f}",
        "warranty_days": days,
        "warranty_until": (
            (row.start.date() + timedelta(days=days)).isoformat()
            if days is not None
            else None
        ),
    }


def attach_repeat(session: Session, lead: Lead, address: str, phone: str) -> None:
    summary = history_summary(session, address, phone, lead.order_at)
    lead.is_repeat = summary is not None
    # Contact-only match can refer to another property; keep object assignment explicit.


def price_hint(
    session: Session, pest: str, area_unit: str, city: str
) -> dict[str, object]:
    rows = [
        row
        for row in session.scalars(
            select(GnomRecord).where(
                GnomRecord.finished.is_(True),
                GnomRecord.cancelled.is_(False),
                GnomRecord.income > 0,
            )
        )
        if pest in row.signals.get("pests", [])
        and row.signals.get("area_unit") == area_unit
        and row.signals.get("city") == canonical(city)
    ]
    return {
        "sample_count": len(rows),
        "median_price": f"{median([row.income for row in rows]):.2f}" if rows else None,
        "label": "Справочно по истории владельца; цена не подставляется",
    }


def _existing_object(
    session: Session, row: GnomRow, phone_hash: str, address_hash: str
) -> Object | None:
    record = session.scalar(
        select(GnomRecord).where(
            GnomRecord.phone_hash == phone_hash, GnomRecord.address_hash == address_hash
        )
    )
    if record:
        return session.get(Object, record.object_id)
    # Match pre-import Core objects only when both decrypted identities agree.
    for obj in session.scalars(select(Object).where(Object.client_id.is_not(None))):
        client = session.get(Client, obj.client_id)
        if not client:
            continue
        try:
            address = (
                decrypt_sensitive_mapping(obj.encrypted_address).get("address") or ""
            )
            phone = decrypt_sensitive_mapping(client.encrypted_pii).get("phone") or ""
            if normalized_address(address) == normalized_address(row.address) and set(
                phones(phone)
            ).intersection(row.phone_values):
                return obj
        except ValueError:
            continue
    return None


def _candidate(session: Session, kind: str, value: str) -> None:
    value = value.strip()
    if not value:
        return
    fingerprint = private_hash("candidate", kind + ":" + canonical(value))
    if (
        session.scalar(
            select(GnomCandidate.id).where(GnomCandidate.fingerprint == fingerprint)
        )
        is None
    ):
        session.add(
            GnomCandidate(
                fingerprint=fingerprint,
                kind=kind,
                encrypted_value=encrypted({"value": value}),
                status="pending",
            )
        )
        session.flush()


def upsert_row(session: Session, row: GnomRow) -> str:
    identity, phone_hash, address_hash = signature(row)
    record = session.scalar(select(GnomRecord).where(GnomRecord.signature == identity))
    content_hash = private_hash(
        "row",
        json.dumps(
            {
                "comments": row.comments,
                "signals": row.signals,
                "income": str(row.income),
                "outcome": str(row.outcome),
                "created": str(row.created),
                "finished": row.finished,
                "cancelled": row.cancelled,
            },
            sort_keys=True,
            ensure_ascii=False,
        ),
    )
    if record and record.content_hash == content_hash:
        return "unchanged"
    if record is None:
        obj = _existing_object(session, row, phone_hash, address_hash)
        if obj is None:
            client = Client(
                name="Клиент ***",
                phone="***",
                client_type="individual",
                encrypted_pii=encrypted(
                    {"name": row.name, "phone": "; ".join(row.phone_values)}
                ),
            )
            session.add(client)
            session.flush()
            area = (
                Decimal(str(row.signals["area_value"]))
                if row.signals.get("area_unit") == "m2"
                and row.signals.get("area_value")
                else Decimal("0")
            )
            obj = Object(
                name="Объект из истории",
                address="***",
                encrypted_address=encrypted({"address": row.address}),
                type=(
                    "apartment" if row.signals.get("area_unit") == "rooms" else "other"
                ),
                area_sqm=area,
                risk_points=[],
                status="active",
                client_id=client.id,
            )
            session.add(obj)
            session.flush()
        assert obj.client_id is not None
        lead = Lead(
            source=str(row.signals["source"]),
            amount=row.income,
            performed_by="Не указан (история)",
        )
        session.add(lead)
        session.flush()
        record = GnomRecord(
            signature=identity,
            content_hash=content_hash,
            phone_hash=phone_hash,
            phone_hashes=[],
            address_hash=address_hash,
            lead_id=lead.id,
            object_id=obj.id,
            client_id=obj.client_id,
            signals={},
            source=str(row.signals["source"]),
            income=row.income,
            outcome=row.outcome,
            start=row.start,
            finished=row.finished,
            cancelled=row.cancelled,
            expense_confirmed=False,
        )
        session.add(record)
        action = "created"
    else:
        existing_lead = session.get(Lead, record.lead_id)
        assert existing_lead is not None
        lead = existing_lead
        obj = session.get(Object, record.object_id)
        assert lead is not None and obj is not None
        if record.outcome != row.outcome or record.signals.get(
            "expense_category"
        ) != row.signals.get("expense_category"):
            record.expense_confirmed = False
        action = "updated"
    lead.source = str(row.signals["source"])
    lead.external_id = str(row.signals["deal_id"]) if row.signals["deal_id"] else None
    lead.order_at = row.start
    lead.created_at = row.created or row.start
    lead.execution_date = row.start.date()
    lead.object_id = obj.id
    lead.client_name = "***"
    lead.phone = "***"
    lead.address = "***"
    lead.raw_text = "***"
    lead.comment = "Из истории Гном: ***"
    lead.encrypted_pii = encrypted(
        {
            "client_name": row.name,
            "phone": "; ".join(row.phone_values),
            "address": row.address,
            "comment": row.comments,
            "raw_text": row.comments,
        }
    )
    lead.reason = ", ".join(str(pest) for pest in row.signals.get("pests", []))
    lead.area = (
        str(row.signals["area_value"]) + " " + str(row.signals["area_unit"])
        if row.signals.get("area_value")
        else None
    )
    lead.contract = "да" if row.signals["contract"] else None
    lead.partner = None
    lead.status = "cancelled" if row.cancelled else "done" if row.finished else "new"
    lead.closed_at = row.start if row.finished or row.cancelled else None
    lead.amount = row.income
    lead.amount_note = f"{row.income:.2f}"
    lead.category = (
        "Доход от агрегаторов" if lead.source == "aggregator" else "Другие работы"
    )
    lead.is_repeat = bool(row.signals["repeat"]) or bool(
        matching_history(session, row.address, " ".join(row.phone_values), row.start)
    )
    record.phone_hashes = [private_hash("phone", value) for value in row.phone_values]
    record.content_hash = content_hash
    record.signals = {
        key: value for key, value in row.signals.items() if key != "chemical_candidates"
    }
    record.source = lead.source
    record.deal_id = lead.external_id
    record.income = row.income
    record.outcome = row.outcome
    record.start, record.created = row.start, row.created
    record.finished, record.cancelled = row.finished, row.cancelled
    if record.platform is None and record.deal_id:
        rules = sorted(
            session.scalars(select(GnomPlatformRule)),
            key=lambda rule: len(rule.deal_prefix),
            reverse=True,
        )
        record.platform = next(
            (
                rule.platform
                for rule in rules
                if record.deal_id.startswith(rule.deal_prefix)
            ),
            None,
        )
    if row.income > 0:
        transaction = (
            session.get(Transaction, record.income_id) if record.income_id else None
        )
        if transaction is None:
            transaction = Transaction(
                source="gnom",
                amount=row.income,
                operation_date=row.start.date(),
                kind="income",
                lead_id=lead.id,
                object_id=obj.id,
                client_id=record.client_id,
                review_required=False,
                description="Доход из истории Гном",
                category=lead.category,
            )
            session.add(transaction)
            session.flush()
            record.income_id = transaction.id
        transaction.amount, transaction.operation_date = row.income, row.start.date()
        transaction.marketing_source = (
            "aggregators"
            if record.source == "aggregator"
            else "yandex_direct" if record.source == "yandex" else record.source
        )
    elif record.income_id:
        # Retain the audit link when a corrected export zeroes the income.
        transaction = session.get(Transaction, record.income_id)
        assert transaction is not None
        transaction.amount = Decimal("0.00")
    if row.finished and not row.cancelled:
        treatment = (
            session.get(Treatment, record.treatment_id) if record.treatment_id else None
        )
        if treatment is None:
            treatment = Treatment(
                object_id=obj.id,
                lead_id=lead.id,
                performed_by="Не указан (история)",
                performed_at=row.start,
                chemicals_used=[],
            )
            session.add(treatment)
            session.flush()
            record.treatment_id = treatment.id
        treatment.performed_at = row.start
        treatment.notes = json.dumps(
            {
                "pests": record.signals["pests"],
                "methods": record.signals["methods"],
                "price": f"{row.income:.2f}",
            },
            ensure_ascii=False,
        )
        obj.last_treatment_date = max(
            obj.last_treatment_date or row.start.date(), row.start.date()
        )
    elif record.treatment_id:
        treatment = session.get(Treatment, record.treatment_id)
        removed_date = treatment.performed_at.date() if treatment else None
        record.treatment_id = None
        session.flush()
        if treatment:
            session.delete(treatment)
        session.flush()
        if removed_date and obj.last_treatment_date == removed_date:
            remaining = session.scalar(
                select(Treatment.performed_at)
                .where(Treatment.object_id == obj.id)
                .order_by(Treatment.performed_at.desc())
                .limit(1)
            )
            obj.last_treatment_date = remaining.date() if remaining else None
    for kind, values in (
        ("chemical", row.signals.get("chemical_candidates", [])),
        ("method", row.signals["methods"]),
        ("condition", row.signals["conditions"]),
    ):
        for value in values:
            _candidate(session, kind, str(value))
    session.flush()
    return action


def import_file(
    engine: Engine, content: bytes, filename: str, *, authorized: bool = False
) -> dict[str, int | str]:
    if not authorized:
        raise GnomError("Импорт требует команды владельца")
    digest = hashlib.sha256(content).hexdigest()
    suffix = Path(filename).suffix.lower()
    safe_name = (
        "gnom-"
        + digest[:16]
        + (suffix if suffix in {".xlsx", ".csv", ".xls"} else ".data")
    )
    counts = {"created": 0, "updated": 0, "unchanged": 0}
    try:
        rows = parse_gnom(content)
        with Session(engine) as session, session.begin():
            if engine.dialect.name == "sqlite":
                from sqlalchemy import text

                session.execute(text("BEGIN IMMEDIATE"))
            seen: dict[str, GnomRow] = {}
            for row in sorted(rows, key=lambda item: item.start):
                identity = signature(row)[0]
                if identity in seen and seen[identity] != row:
                    raise GnomError("Разные строки имеют одинаковую сигнатуру")
                seen[identity] = row
                counts[upsert_row(session, row)] += 1
            run = GnomImportRun(
                filename=safe_name, file_hash=digest, rows=len(rows), status="success"
            )
            session.add(run)
            session.flush()
            result: dict[str, int | str] = {
                "run_id": run.id,
                "rows": len(rows),
                **counts,
            }
        return result
    except Exception as error:
        safe_error = (
            str(error)
            if isinstance(error, GnomError)
            else "Импорт отклонён; данные файла не применены"
        )
        with Session(engine) as session, session.begin():
            session.add(
                GnomImportRun(
                    filename=safe_name,
                    file_hash=digest,
                    rows=0,
                    status="failed",
                    error=safe_error,
                )
            )
        raise GnomError(safe_error) from None


def confirm_expense(
    session: Session, record: GnomRecord, category_id: int
) -> Transaction:
    category = session.get(TransactionCategory, category_id)
    if not category or category.kind != "expense" or not category.is_active:
        raise GnomError("Выберите активную расходную категорию")
    if record.expense_confirmed and record.expense_id:
        result = session.get(Transaction, record.expense_id)
        assert result is not None
        return result
    transaction = (
        session.get(Transaction, record.expense_id) if record.expense_id else None
    )
    if transaction is None:
        if record.outcome <= 0:
            raise GnomError("В строке нет расхода")
        transaction = Transaction(
            source="gnom",
            amount=record.outcome,
            operation_date=record.start.date(),
            kind="expense",
            lead_id=record.lead_id,
            object_id=record.object_id,
            client_id=record.client_id,
            description="Подтверждённый расход из истории Гном",
            review_required=False,
        )
        session.add(transaction)
        session.flush()
        record.expense_id = transaction.id
    transaction.amount, transaction.category_id, transaction.category = (
        record.outcome,
        category.id,
        category.title,
    )
    record.expense_confirmed = True
    return transaction


def analytics(session: Session) -> dict[str, object]:
    rows = list(session.scalars(select(GnomRecord)))
    sources: dict[str, dict[str, int]] = {}
    months: dict[str, Decimal] = {}
    pests: dict[str, int] = {}
    objects: dict[str, int] = {}
    lead_times: list[Decimal] = []
    deals: dict[str, dict[str, object]] = {}
    for row in rows:
        year = str(row.start.year)
        sources.setdefault(year, {})[row.source] = (
            sources.setdefault(year, {}).get(row.source, 0) + 1
        )
        month = row.start.strftime("%Y-%m")
        months[month] = months.get(month, Decimal("0.00")) + row.income
        if row.finished and not row.cancelled:
            key = f"Объект #{row.object_id}"
            objects[key] = objects.get(key, 0) + 1
        for pest in row.signals.get("pests", []):
            pests[str(pest)] = pests.get(str(pest), 0) + 1
        if row.created and row.start >= row.created:
            lead_times.append(
                Decimal(str((row.start - row.created).total_seconds())) / Decimal(3600)
            )
        if row.source == "aggregator":
            key = row.deal_id or f"без номера/{row.id}"
            deal = deals.setdefault(
                key,
                {
                    "deal_id": row.deal_id,
                    "record_id": row.id,
                    "platform": row.platform,
                    "revenue": "0.00",
                    "count": 0,
                },
            )
            deal["revenue"] = f"{Decimal(str(deal['revenue'])) + row.income:.2f}"
            deal["count"] = int(str(deal["count"])) + 1
    paid = [row.income for row in rows if row.income > 0]
    return {
        "sources_by_year": sources,
        "revenue_by_month": {
            key: f"{value:.2f}" for key, value in sorted(months.items())
        },
        "pests": pests,
        "repeat_objects": dict(
            sorted(
                ((key, value) for key, value in objects.items() if value > 1),
                key=lambda pair: -pair[1],
            )[:20]
        ),
        "average_check": f"{sum(paid) / len(paid):.2f}" if paid else None,
        "lead_time_hours": (
            f"{sum(lead_times) / len(lead_times):.2f}" if lead_times else None
        ),
        "rescheduled": sum(bool(row.signals.get("rescheduled")) for row in rows),
        "aggregators": list(deals.values()),
    }
