"""Isolated, consent-first client conversation; never executes staff commands."""

import hashlib
import hmac
import os
import re
import sys
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import cast

from sqlalchemy import delete, update
from sqlalchemy.engine import CursorResult, Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Lead, TelegramClientDraft
from app.security.pii import (
    decrypt_sensitive_mapping,
    encrypt_sensitive_mapping,
    protect_lead_pii,
)

START_SOURCES = {
    "m_vk": "vk",
    "m_avito": "avito",
    "m_yandex_direct": "yandex_direct",
    "m_seo": "seo",
    "m_site": "other",
}
UNAVAILABLE = "Приём заявок временно недоступен. Позвоните 8 (921) 472-50-00."
MAX_MESSAGES_PER_WINDOW = 20
RATE_WINDOW = timedelta(minutes=10)
RATE_LIMITED = "Слишком много сообщений. Подождите 10 минут или напишите /cancel."


def _safe_alert_value(value: str) -> str:
    # Drop phone-like digit sequences even if pasted into address or campaign.
    return re.sub(r"\+?\d(?:[\s()._-]*\d){6,}", "[контакт скрыт]", value)[:300]


def _owner_alert(
    campaign: str, description: str = "", lead_id: int | None = None
) -> str:
    address = re.search(r"(?:^|\n)адрес\s*:\s*([^\n]+)", description, re.I)
    pest = re.search(
        r"(?:^|\n)(?:вредитель|что нужно решить\?)\s*:\s*([^\n]+)", description, re.I
    )
    return (
        (f"Новая заявка из квиза #{lead_id}" if lead_id else "Новый черновик квиза")
        + f"\nАдрес: {_safe_alert_value(address[1]) if address else 'ещё не указан'}"
        + f"\nВредитель: {_safe_alert_value(pest[1]) if pest else 'ещё не указан'}"
        + f"\nCampaign: {_safe_alert_value(campaign)}"
    )


def purge_expired_client_drafts(engine: Engine, *, now: datetime) -> int:
    """Delete abandoned encrypted drafts without waiting for another message."""
    with Session(engine) as session:
        result = session.execute(
            delete(TelegramClientDraft).where(TelegramClientDraft.expires_at <= now)
        )
        deleted = cast(CursorResult, result).rowcount
        session.commit()
        return deleted


def receive_client_message(
    engine: Engine,
    *,
    chat_id: int,
    sender_id: int,
    text: str,
    update_id: int,
    now: datetime,
    is_staff: bool = False,
    is_private: bool = True,
    notify_owner: Callable[[str], bool] | None = None,
) -> str | None:
    if is_staff or not is_private or chat_id != sender_id:
        return None
    text = text.strip()
    parts = text.split()
    campaign = (
        parts[1][5:]
        if len(parts) == 2
        and parts[0] == "/start"
        and re.fullmatch(r"quiz_[A-Za-z0-9_-]{1,59}", parts[1])
        else None
    )
    source = (
        START_SOURCES.get(parts[1])
        if len(parts) == 2 and parts[0] == "/start"
        else None
    )
    if campaign is not None:
        source = START_SOURCES.get("m_" + campaign, "other")
    elif source:
        campaign = parts[1][2:]
    alert: str | None = None
    encrypted_empty = encrypt_sensitive_mapping({})
    if not encrypted_empty:
        return UNAVAILABLE if source else None
    key = hmac.new(
        os.environ["PII_FERNET_KEY"].strip().encode(),
        f"client-chat:{chat_id}".encode(),
        hashlib.sha256,
    ).hexdigest()
    with Session(engine) as session:
        draft = session.get(TelegramClientDraft, key)
        if draft is None:
            if source is None:
                return None
            draft = TelegramClientDraft(
                chat_key=key,
                source=source,
                step="consent",
                encrypted_payload=encrypted_empty,
                last_update_id=update_id,
                last_reply=None,
                expires_at=now + timedelta(hours=24),
                window_started=now,
                message_count=1,
            )
            session.add(draft)
            try:
                session.flush()
            except IntegrityError:
                session.rollback()
                return None
            alert = _owner_alert(campaign or "site")
        else:
            if update_id <= draft.last_update_id:
                return draft.last_reply or ""
            # Compare-and-set serializes replay/concurrent delivery in SQLite too.
            claimed = session.execute(
                update(TelegramClientDraft)
                .where(
                    TelegramClientDraft.chat_key == key,
                    TelegramClientDraft.last_update_id < update_id,
                )
                .values(last_update_id=update_id)
            )
            if cast(CursorResult, claimed).rowcount != 1:
                session.refresh(draft)
                return draft.last_reply or ""
            session.refresh(draft)
            if now - draft.window_started >= RATE_WINDOW:
                draft.window_started = now
                draft.message_count = 1
            elif text != "/cancel":
                if draft.message_count >= MAX_MESSAGES_PER_WINDOW:
                    draft.last_reply = RATE_LIMITED
                    session.commit()
                    return RATE_LIMITED
                draft.message_count += 1
        if source:
            if draft.accepted_at and now - draft.accepted_at < timedelta(minutes=10):
                draft.last_reply = (
                    "Заявка уже принята. Для новой задачи "
                    "повторите обращение через 10 минут."
                )
                session.commit()
                return draft.last_reply
            draft.source, draft.step = source, "consent"
            draft.encrypted_payload = (
                encrypt_sensitive_mapping({"campaign": campaign}) or encrypted_empty
            )
            draft.expires_at = now + timedelta(hours=24)
            reply = (
                "Клиентский приём ЭКОДЕЗ. Для ответа на обращение сохраним описание "
                "и телефон в защищённой системе владельца. Не присылайте документы "
                "и медицинские сведения. Черновик действует 24 часа. "
                "Для отмены: /cancel. Если согласны передать сведения для ответа "
                "на заявку, напишите СОГЛАСЕН. Рекламной рассылки не будет."
            )
        elif text == "/cancel" and draft.step == "submitted":
            reply = (
                "Черновика уже нет, обращение передано владельцу. "
                "Для отмены обращения или удаления его данных "
                "свяжитесь по номеру 8 (921) 472-50-00."
            )
        elif text == "/cancel":
            draft.step, draft.encrypted_payload = "cancelled", encrypted_empty
            reply = "Черновик отменён, его описание и контакт удалены."
        elif now >= draft.expires_at:
            draft.step, draft.encrypted_payload = "expired", encrypted_empty
            reply = "Срок черновика истёк. Начните заново по ссылке квиза."
        elif draft.step in ("submitted", "cancelled", "expired"):
            reply = "Активного черновика нет. Новую заявку начните по ссылке квиза."
        elif draft.step == "consent":
            if text.upper() != "СОГЛАСЕН":
                reply = "Для продолжения напишите СОГЛАСЕН или /cancel."
            else:
                draft.step = "description"
                reply = (
                    "Пришлите скопированные ответы квиза или описание задачи "
                    "(до 2000 знаков). Точный адрес пока не нужен."
                )
        elif draft.step == "description":
            if not 5 <= len(text) <= 2000 or text.startswith("/"):
                reply = "Нужно описание задачи от 5 до 2000 знаков или /cancel."
            else:
                metadata = decrypt_sensitive_mapping(draft.encrypted_payload)
                metadata["description"] = text
                draft.encrypted_payload = (
                    encrypt_sensitive_mapping(metadata) or encrypted_empty
                )
                draft.step = "phone"
                reply = "Укажите телефон для ответа, например +7 (999) 123-45-67."
        else:
            try:
                payload = decrypt_sensitive_mapping(draft.encrypted_payload)
            except ValueError:
                session.rollback()
                return UNAVAILABLE
            if draft.step == "phone":
                digits = re.sub(r"[\s()+-]", "", text)
                if not re.fullmatch(r"[78]\d{10}", digits):
                    reply = "Проверьте телефон: 11 цифр, начало 7 или 8."
                else:
                    payload["phone"] = "+7" + digits[1:]
                    draft.encrypted_payload = (
                        encrypt_sensitive_mapping(payload) or encrypted_empty
                    )
                    draft.step = "confirm"
                    reply = (
                        "Описание и телефон сохранены в черновике. "
                        "Для передачи владельцу напишите ОТПРАВИТЬ, "
                        "для отмены /cancel. Стоимость и время ещё не согласованы."
                    )
            elif text.upper() != "ОТПРАВИТЬ":
                reply = "Напишите ОТПРАВИТЬ для подтверждения или /cancel."
            else:
                full = {
                    "phone": payload.get("phone"),
                    "comment": payload.get("description"),
                }
                protected = protect_lead_pii(full, payload.get("description") or "")
                lead = Lead(
                    source=draft.source,
                    created_at=now,
                    status="new",
                    phone=protected["phone"],
                    comment=protected["comment"],
                    raw_text=protected["raw_text"],
                    encrypted_pii=protected["encrypted_pii"],
                    reason="Обращение из квиза",
                )
                session.add(lead)
                session.flush()
                alert = _owner_alert(
                    payload.get("campaign") or draft.source,
                    payload.get("description") or "",
                    lead.id,
                )
                draft.step, draft.encrypted_payload = "submitted", encrypted_empty
                draft.accepted_at = now
                reply = (
                    "Заявка принята и передана владельцу в системе. "
                    "Стоимость и время подтвердит специалист."
                )
        draft.last_reply = reply
        session.commit()
        if alert is not None and notify_owner is not None:
            try:
                if not notify_owner(alert):
                    print("quiz_owner_alert_failed", file=sys.stderr)
            except Exception as error:
                print(
                    f"quiz_owner_alert_failed: {type(error).__name__}", file=sys.stderr
                )
        return reply
