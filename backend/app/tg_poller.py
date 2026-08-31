import json
import os
import re
import sys
import threading
import time
import traceback
import urllib.parse
import urllib.request
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, cast

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.finance_categories import (
    INCOME_CATEGORIES_V1,
    classify_finance,
    default_finance_category,
)
from app.inventory import ChemicalUsageIn
from app.lead_parser import parse_amount_note, parse_order_text
from app.master_workflow import (
    InvalidCompletion,
    InvalidExecutionDate,
    complete_lead,
    list_due_leads,
    moscow_today,
    reschedule_lead,
)
from app.models import Inventory, Lead, TelegramMasterDraft, Transaction
from app.security.pii import (
    decrypt_pii,
    mask_address,
    mask_name,
    protect_lead_pii,
)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OFFSET_FILE = os.path.join(BASE_DIR, "tg_offset.json")
_poller_started = False
ATTACHMENTS_DIR = os.path.join(BASE_DIR, "attachments")

_AMOUNT_RE = re.compile(
    r"(?<!\d)(\d{1,3}(?:[ \u00a0]\d{3})+|\d+)(?:[.,](\d{1,2}))?(?!\d)"
)


def _load_offset() -> int:
    try:
        with open(OFFSET_FILE, encoding="utf-8") as f:
            return int(json.load(f).get("offset", 0))
    except Exception:
        return 0


def _save_offset(value: int) -> None:
    try:
        with open(OFFSET_FILE, "w", encoding="utf-8") as f:
            json.dump({"offset": value}, f)
    except Exception:
        pass


def _ingest(engine, text: str) -> str | None:
    data = parse_order_text(text)
    if not data["external_id"]:
        return None
    with Session(engine) as session:
        existing = session.scalar(
            select(Lead).where(Lead.external_id == data["external_id"])
        )
        if existing is not None:
            return "duplicate"
        protected = protect_lead_pii(data, text)
        row = Lead(
            source="telegram",
            external_id=data["external_id"] or None,
            order_at=data["order_at"],
            client_name=protected["client_name"],
            phone=protected["phone"],
            address=protected["address"],
            area=data["area"] or None,
            reason=data["reason"] or None,
            comment=protected["comment"],
            amount_note=data["amount_note"] or None,
            contract=data["contract"] or None,
            partner=data["partner"] or None,
            status="new",
            amount=parse_amount_note(data["amount_note"]),
            execution_date=data["order_at"].date() if data["order_at"] else None,
            performed_by="Артём",
            raw_text=protected["raw_text"],
            encrypted_pii=protected["encrypted_pii"],
        )
        session.add(row)
        session.commit()
        print(
            json.dumps(
                {
                    "event": "lead_ingested",
                    "external_id": data["external_id"],
                },
                ensure_ascii=False,
            )
        )
        return "created"


def _send_message(
    token: str,
    chat_id: int,
    text: str,
    *,
    reply_markup: dict | None = None,
) -> bool:
    url = "https://api.telegram.org/bot" + token + "/sendMessage"
    payload = {"chat_id": chat_id, "text": text}
    if reply_markup is not None:
        payload["reply_markup"] = reply_markup
    body = json.dumps(payload).encode("utf-8")
    for attempt in range(1, 4):
        try:
            request = urllib.request.Request(
                url,
                data=body,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(request, timeout=15) as r:
                payload = json.loads(r.read().decode("utf-8"))
            if not payload.get("ok"):
                raise RuntimeError("Telegram sendMessage returned ok=false")
            return True
        except Exception as exc:
            print(
                "TG sendMessage failed: " f"{type(exc).__name__}, attempt {attempt}/3",
                file=sys.stderr,
            )
            if attempt < 3:
                time.sleep(3)
    return False


def send_message(token: str, chat_id: int, text: str) -> bool:
    """Отправить обычное Telegram-сообщение без клавиатуры."""
    return _send_message(token, chat_id, text)


def _telegram_post(token: str, method: str, payload: dict) -> bool:
    url = "https://api.telegram.org/bot" + token + "/" + method
    body = json.dumps(payload).encode("utf-8")
    for attempt in range(1, 4):
        try:
            request = urllib.request.Request(
                url,
                data=body,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(request, timeout=15) as response:
                result = json.loads(response.read().decode("utf-8"))
            if not result.get("ok"):
                raise RuntimeError(f"Telegram {method} returned ok=false")
            return True
        except Exception as exc:
            print(
                f"TG {method} failed: {type(exc).__name__}, attempt {attempt}/3",
                file=sys.stderr,
            )
            if attempt < 3:
                time.sleep(3)
    return False


def _answer_callback_query(token: str, callback_query_id: str) -> bool:
    return _telegram_post(
        token,
        "answerCallbackQuery",
        {"callback_query_id": callback_query_id},
    )


def _edit_message(
    token: str,
    chat_id: int,
    message_id: int,
    text: str,
) -> bool:
    return _telegram_post(
        token,
        "editMessageText",
        {"chat_id": chat_id, "message_id": message_id, "text": text},
    )


def _allowed_sender_ids() -> set[int]:
    return set(_allowed_sender_roles())


def _allowed_sender_roles() -> dict[int, str]:
    allowed: dict[int, str] = {}
    for name, role in (("OWNER_TG_ID", "owner"), ("ALEXEY_TG_ID", "alexey")):
        value = os.getenv(name, "").strip()
        if value:
            try:
                allowed[int(value)] = role
            except ValueError:
                print(f"TG agent: {name} is not numeric, ignored", file=sys.stderr)
    return allowed


def _lead_pii(lead: Lead) -> tuple[str, str, str]:
    try:
        full = decrypt_pii(lead.encrypted_pii)
    except ValueError:
        full = {}
    return (
        str(full.get("client_name") or lead.client_name or "не указано"),
        str(full.get("phone") or lead.phone or "не указано"),
        str(full.get("address") or lead.address or "не указано"),
    )


def _send_today(token: str, engine, chat_id: int) -> None:
    today = moscow_today()
    with Session(engine) as session:
        leads = list_due_leads(session, today)
        if not leads:
            _send_message(token, chat_id, "Работы на сегодня: нет")
            return
        _send_message(token, chat_id, "Работы на сегодня")
        send_due_lead_cards(token, chat_id, leads)


def send_due_lead_cards(
    token: str,
    chat_id: int,
    leads: list[Lead],
    *,
    sender=None,
) -> bool:
    effective_sender = sender or _send_message
    delivered = True
    for lead in leads:
        name, phone, address = _lead_pii(lead)
        due = lead.execution_date.strftime("%d.%m.%Y") if lead.execution_date else "—"
        delivered = (
            effective_sender(
                token,
                chat_id,
                f"Заявка #{lead.id} · {due}\n{name}\n{phone}\n{address}",
                reply_markup={
                    "inline_keyboard": [
                        [
                            {
                                "text": "Выполнено",
                                "callback_data": f"mw:done:{lead.id}",
                            },
                            {
                                "text": "Перенести",
                                "callback_data": f"mw:move:{lead.id}",
                            },
                        ]
                    ]
                },
            )
            and delivered
        )
    return delivered


def _replace_draft(
    session: Session,
    *,
    actor_key: str,
    lead_id: int,
    action: str,
    step: str,
    payload: dict[str, object] | None = None,
) -> TelegramMasterDraft:
    draft = session.scalar(
        select(TelegramMasterDraft).where(TelegramMasterDraft.actor_key == actor_key)
    )
    if draft is None:
        draft = TelegramMasterDraft(
            actor_key=actor_key,
            lead_id=lead_id,
            action=action,
            step=step,
            payload=payload or {},
        )
        session.add(draft)
    else:
        draft.lead_id = lead_id
        draft.action = action
        draft.step = step
        draft.payload = payload or {}
        draft.updated_at = datetime.now(UTC)
    session.commit()
    session.refresh(draft)
    return draft


def _draft(session: Session, actor_key: str) -> TelegramMasterDraft | None:
    return session.scalar(
        select(TelegramMasterDraft).where(TelegramMasterDraft.actor_key == actor_key)
    )


def _category_keyboard() -> dict:
    rows = [
        [{"text": category, "callback_data": f"mw:cat:{index}"}]
        for index, category in enumerate(INCOME_CATEGORIES_V1)
    ]
    return {"inline_keyboard": rows}


def _inventory_keyboard(session: Session, *, allow_without_materials: bool) -> dict:
    items = session.scalars(
        select(Inventory)
        .where(Inventory.quantity > 0)
        .order_by(Inventory.chemical_name)
    ).all()
    rows = [
        [
            {
                "text": f"{item.chemical_name} ({item.quantity:.3f} {item.unit})",
                "callback_data": f"mw:inv:{item.id}",
            }
        ]
        for item in items
    ]
    if allow_without_materials:
        rows.append([{"text": "Без материалов", "callback_data": "mw:none"}])
    return {"inline_keyboard": rows}


def _completion_confirmation(
    session: Session,
    draft: TelegramMasterDraft,
    payload: dict[str, Any],
) -> str:
    lines = [
        f"Заявка #{draft.lead_id}",
        f"Категория: {payload.get('category') or 'Другие работы'}",
        f"Исполнитель: {payload.get('performed_by') or 'Артём'}",
        "Материалы:",
    ]
    usage_rows = cast(list[dict[str, object]], payload.get("usages") or [])
    if not usage_rows:
        lines.append("• без списания")
    for item in usage_rows:
        inventory_id = int(str(item["inventory_id"]))
        inventory = session.get(Inventory, inventory_id)
        name = inventory.chemical_name if inventory is not None else f"#{inventory_id}"
        lines.append(f"• {name}: {item['quantity']}")
    lines.append("Подтвердить выполнение?")
    return "\n".join(lines)


def _confirmation_keyboard() -> dict:
    return {
        "inline_keyboard": [
            [
                {"text": "Подтвердить", "callback_data": "mw:confirm"},
                {"text": "Отмена", "callback_data": "mw:cancel"},
            ]
        ]
    }


def _handle_master_text(
    token: str,
    engine,
    message: dict,
    actor_key: str,
) -> bool:
    chat_id = (message.get("chat") or {}).get("id")
    text = str(message.get("text") or "").strip()
    if chat_id is None or not text:
        return False
    with Session(engine) as session:
        draft = _draft(session, actor_key)
        if draft is None:
            return False
        if draft.action == "reschedule" and draft.step == "custom_date":
            try:
                new_date = datetime.strptime(text, "%d.%m.%Y").date()
                reschedule_lead(session, draft.lead_id, new_date, moscow_today())
            except (ValueError, InvalidExecutionDate):
                _send_message(
                    token,
                    chat_id,
                    "Введите дату в формате ДД.ММ.ГГГГ, не раньше сегодня",
                )
                return True
            session.delete(draft)
            session.commit()
            _send_message(token, chat_id, f"Перенесено на {new_date:%d.%m.%Y}")
            return True
        if draft.action == "complete" and draft.step == "quantity":
            try:
                quantity = Decimal(text.replace(" ", "").replace(",", "."))
            except InvalidOperation:
                quantity = Decimal("0")
            payload = cast(dict[str, Any], dict(draft.payload or {}))
            inventory_id = int(payload.get("inventory_id") or 0)
            inventory = session.get(Inventory, inventory_id)
            if inventory is None or quantity <= 0 or quantity > inventory.quantity:
                _send_message(
                    token, chat_id, "Количество некорректно или превышает остаток"
                )
                return True
            quantized = quantity.quantize(Decimal("0.001"))
            if quantized != quantity:
                _send_message(token, chat_id, "Не более 3 знаков после запятой")
                return True
            usages = cast(list[dict[str, object]], list(payload.get("usages") or []))
            usages.append({"inventory_id": inventory_id, "quantity": f"{quantity:.3f}"})
            payload["usages"] = usages
            payload.pop("inventory_id", None)
            draft.payload = payload
            draft.step = "materials"
            session.commit()
            _send_message(
                token,
                chat_id,
                "Материал добавлен",
                reply_markup={
                    "inline_keyboard": [
                        [
                            {"text": "Добавить ещё", "callback_data": "mw:more"},
                            {"text": "Завершить", "callback_data": "mw:finish"},
                        ]
                    ]
                },
            )
            return True
    return False


def _handle_master_callback(
    token: str,
    engine,
    callback: dict,
    actor_key: str,
) -> bool:
    data = str(callback.get("data") or "")
    if not data.startswith("mw:"):
        return False
    chat_id = ((callback.get("message") or {}).get("chat") or {}).get("id")
    if chat_id is None:
        return True
    parts = data.split(":")
    action = parts[1] if len(parts) > 1 else ""
    today = moscow_today()
    with Session(engine) as session:
        if action in ("done", "move") and len(parts) == 3:
            try:
                lead_id = int(parts[2])
            except ValueError:
                return True
            lead = session.get(Lead, lead_id)
            if lead is None:
                return True
            if action == "done":
                _replace_draft(
                    session,
                    actor_key=actor_key,
                    lead_id=lead_id,
                    action="complete",
                    step="category",
                )
                _send_message(
                    token,
                    chat_id,
                    "Выберите категорию",
                    reply_markup=_category_keyboard(),
                )
            else:
                _replace_draft(
                    session,
                    actor_key=actor_key,
                    lead_id=lead_id,
                    action="reschedule",
                    step="date",
                )
                _send_message(
                    token,
                    chat_id,
                    "На какую дату перенести?",
                    reply_markup={
                        "inline_keyboard": [
                            [
                                {"text": "Сегодня", "callback_data": "mw:date:0"},
                                {"text": "Завтра", "callback_data": "mw:date:1"},
                            ],
                            [
                                {"text": "+2 дня", "callback_data": "mw:date:2"},
                                {"text": "+7 дней", "callback_data": "mw:date:7"},
                            ],
                            [{"text": "Своя дата", "callback_data": "mw:date:custom"}],
                        ]
                    },
                )
            return True

        draft = _draft(session, actor_key)
        if draft is None:
            return True
        payload = cast(dict[str, Any], dict(draft.payload or {}))
        if action == "cancel":
            session.delete(draft)
            session.commit()
            _send_message(token, chat_id, "Отменено")
            return True
        if action == "date" and draft.action == "reschedule" and len(parts) == 3:
            if parts[2] == "custom":
                draft.step = "custom_date"
                session.commit()
                _send_message(token, chat_id, "Введите дату ДД.ММ.ГГГГ")
                return True
            try:
                new_date = today + timedelta(days=int(parts[2]))
                reschedule_lead(session, draft.lead_id, new_date, today)
            except (ValueError, InvalidExecutionDate):
                return True
            session.delete(draft)
            session.commit()
            _send_message(token, chat_id, f"Перенесено на {new_date:%d.%m.%Y}")
            return True
        if action == "cat" and draft.step == "category" and len(parts) == 3:
            try:
                payload["category"] = INCOME_CATEGORIES_V1[int(parts[2])]
            except (ValueError, IndexError):
                return True
            draft.payload = payload
            draft.step = "performer"
            session.commit()
            _send_message(
                token,
                chat_id,
                "Кто выполнил?",
                reply_markup={
                    "inline_keyboard": [
                        [
                            {"text": "Артём", "callback_data": "mw:who:artem"},
                            {"text": "Алексей", "callback_data": "mw:who:alexey"},
                        ]
                    ]
                },
            )
            return True
        if action == "who" and draft.step == "performer" and len(parts) == 3:
            performer = {"artem": "Артём", "alexey": "Алексей"}.get(parts[2])
            if performer is None:
                return True
            payload["performed_by"] = performer
            payload["usages"] = []
            draft.payload = payload
            draft.step = "inventory"
            session.commit()
            _send_message(
                token,
                chat_id,
                "Выберите материал",
                reply_markup=_inventory_keyboard(session, allow_without_materials=True),
            )
            return True
        if action in ("more",) and draft.step == "materials":
            draft.step = "inventory"
            session.commit()
            _send_message(
                token,
                chat_id,
                "Выберите материал",
                reply_markup=_inventory_keyboard(
                    session, allow_without_materials=False
                ),
            )
            return True
        if action == "inv" and draft.step == "inventory" and len(parts) == 3:
            try:
                inventory_id = int(parts[2])
            except ValueError:
                return True
            if session.get(Inventory, inventory_id) is None:
                return True
            payload["inventory_id"] = inventory_id
            draft.payload = payload
            draft.step = "quantity"
            session.commit()
            _send_message(token, chat_id, "Введите количество")
            return True
        if action == "none" and draft.step == "inventory":
            payload["without_materials"] = True
            draft.payload = payload
            draft.step = "confirm"
            session.commit()
            _send_message(
                token,
                chat_id,
                _completion_confirmation(session, draft, payload),
                reply_markup=_confirmation_keyboard(),
            )
            return True
        if action == "finish" and draft.step == "materials":
            draft.step = "confirm"
            session.commit()
            _send_message(
                token,
                chat_id,
                _completion_confirmation(session, draft, payload),
                reply_markup=_confirmation_keyboard(),
            )
            return True
        if action == "confirm" and draft.step == "confirm":
            usage_rows = cast(list[dict[str, object]], payload.get("usages") or [])
            usages = [
                ChemicalUsageIn(
                    inventory_id=int(str(item["inventory_id"])),
                    quantity_used=Decimal(str(item["quantity"])),
                )
                for item in usage_rows
            ]
            try:
                result = complete_lead(
                    session,
                    lead_id=draft.lead_id,
                    category=str(payload.get("category") or "Другие работы"),
                    performed_by=str(payload.get("performed_by") or "Артём"),
                    usages=usages,
                    without_materials=bool(payload.get("without_materials", False)),
                    completed_at=datetime.now(UTC),
                )
            except (InvalidCompletion, ValueError):
                _send_message(
                    token, chat_id, "Не удалось завершить: проверьте заявку и остатки"
                )
                return True
            # complete_lead commits; reload the persistent draft before deleting it.
            saved_draft = _draft(session, actor_key)
            if saved_draft is not None:
                session.delete(saved_draft)
                session.commit()
            text = "Уже было выполнено" if result.already_done else "Выполнено"
            _send_message(token, chat_id, text)
            return True
    return True


def _parse_agent_text(text: str) -> tuple[str, Decimal, str]:
    normalized = text.lower()
    if any(
        phrase in normalized for phrase in ("перевели нам", "оплатили нам", "получил")
    ):
        kind = "income"
    elif any(phrase in normalized for phrase in ("купил", "потратил", "оплатил")):
        kind = "expense"
    else:
        kind = "unknown"

    match = _AMOUNT_RE.search(text)
    if match is None:
        amount = Decimal("0.00")
    else:
        whole = match.group(1).replace(" ", "").replace("\u00a0", "")
        fraction = match.group(2)
        amount = Decimal(whole + ("." + fraction if fraction else ""))

    category = classify_finance(text) or default_finance_category(kind)
    return kind, amount, category


def _create_agent_draft(
    engine,
    *,
    description: str,
    kind: str,
    amount: Decimal,
    category: str,
) -> int:
    with Session(engine) as session:
        row = Transaction(
            source="tg_agent",
            operation_date=date.today(),
            amount=amount,
            currency="RUB",
            counterparty=None,
            description=description,
            category=category,
            kind=kind,
            review_required=True,
        )
        session.add(row)
        session.commit()
        session.refresh(row)
        return row.id


def _download_photo(token: str, file_id: str) -> str:
    file_url = (
        "https://api.telegram.org/bot"
        + token
        + "/getFile?file_id="
        + urllib.parse.quote(file_id)
    )
    last_error: Exception | None = None
    for attempt in range(1, 4):
        try:
            with urllib.request.urlopen(file_url, timeout=15) as response:
                payload = json.loads(response.read().decode("utf-8"))
            file_path = (payload.get("result") or {}).get("file_path")
            if not payload.get("ok") or not file_path:
                raise RuntimeError("Telegram getFile returned no file_path")
            download_url = "https://api.telegram.org/file/bot" + token + "/" + file_path
            with urllib.request.urlopen(download_url, timeout=15) as response:
                content = response.read()
            os.makedirs(ATTACHMENTS_DIR, exist_ok=True)
            safe_file_id = re.sub(r"[^A-Za-z0-9_-]", "_", file_id)
            filename = f"{date.today().isoformat()}_{safe_file_id}.jpg"
            saved_path = os.path.join(ATTACHMENTS_DIR, filename)
            with open(saved_path, "wb") as output:
                output.write(content)
            return saved_path
        except Exception as exc:
            last_error = exc
            print(
                "TG photo download failed: "
                f"{type(exc).__name__}, attempt {attempt}/3",
                file=sys.stderr,
            )
            if attempt < 3:
                time.sleep(3)
    raise RuntimeError("Telegram photo download failed") from last_error


def _handle_agent_message(token: str, engine, message: dict) -> None:
    chat_id = (message.get("chat") or {}).get("id")
    if chat_id is None:
        return

    text = message.get("text")
    if text:
        kind, amount, category = _parse_agent_text(text)
        tx_id = _create_agent_draft(
            engine,
            description=text,
            kind=kind,
            amount=amount,
            category=category,
        )
        direction = {
            "income": "доход",
            "expense": "расход",
            "unknown": "неизвестно",
        }[kind]
        keyboard = {
            "inline_keyboard": [
                [
                    {"text": "Подтвердить", "callback_data": f"ok:{tx_id}"},
                    {"text": "Отклонить", "callback_data": f"no:{tx_id}"},
                ]
            ]
        }
        _send_message(
            token,
            chat_id,
            f"Черновик: {direction} {format(amount, 'f')} {category}",
            reply_markup=keyboard,
        )
        return

    photos = message.get("photo") or []
    if photos:
        file_id = photos[-1].get("file_id")
        if not file_id:
            return
        saved_path = _download_photo(token, file_id)
        caption = message.get("caption") or ""
        description = f"фото: {saved_path}"
        if caption:
            description += "\n" + caption
        _create_agent_draft(
            engine,
            description=description,
            kind="unknown",
            amount=Decimal("0.00"),
            category="Прочее",
        )
        _send_message(
            token,
            chat_id,
            "Фото принято, черновик в пульте на проверке",
        )
        return

    _send_message(
        token,
        chat_id,
        "Голосовые пока продублируйте текстом (распознавание — в следующей версии)",
    )


def _handle_callback(
    token: str,
    engine,
    callback: dict,
    allowed_ids: set[int],
) -> None:
    callback_id = str(callback.get("id") or "")
    _answer_callback_query(token, callback_id)

    sender_id = (callback.get("from") or {}).get("id")
    if sender_id not in allowed_ids:
        return
    data = str(callback.get("data") or "")
    try:
        action, raw_id = data.split(":", 1)
        tx_id = int(raw_id)
    except (ValueError, TypeError):
        return
    if action not in ("ok", "no"):
        return

    with Session(engine) as session:
        row = session.get(Transaction, tx_id)
        if row is None or row.source != "tg_agent":
            return
        if action == "ok":
            row.review_required = False
            result_text = "✅ Проведено"
        else:
            session.delete(row)
            result_text = "❌ Отклонено"
        session.commit()

    callback_message = callback.get("message") or {}
    chat_id = (callback_message.get("chat") or {}).get("id")
    message_id = callback_message.get("message_id")
    if chat_id is not None and message_id is not None:
        _edit_message(token, chat_id, message_id, result_text)


def _process_update(
    token: str,
    engine,
    update: dict,
    allowed_roles: dict[int, str],
) -> None:
    callback = update.get("callback_query")
    if callback is not None:
        sender_value = (callback.get("from") or {}).get("id")
        sender_id = sender_value if isinstance(sender_value, int) else None
        callback_data = str(callback.get("data") or "")
        if callback_data.startswith("mw:"):
            _answer_callback_query(token, str(callback.get("id") or ""))
            actor_key = allowed_roles.get(sender_id) if sender_id is not None else None
            if actor_key is not None:
                _handle_master_callback(token, engine, callback, actor_key)
            return
        _handle_callback(token, engine, callback, set(allowed_roles))
        return

    channel_post = update.get("channel_post")
    message = update.get("message")
    msg = channel_post or message or {}
    text = str(msg.get("text") or "")
    command = text.split(maxsplit=1)[0].split("@")[0] if text else ""
    chat_id = (msg.get("chat") or {}).get("id")
    sender_value = (msg.get("from") or {}).get("id")
    sender_id = sender_value if isinstance(sender_value, int) else None
    actor_key = allowed_roles.get(sender_id) if sender_id is not None else None

    if message is not None and command == "/whoami":
        if chat_id is not None:
            _send_message(token, chat_id, str(chat_id))
        return
    if message is not None and command == "/today":
        if actor_key is not None and chat_id is not None:
            _send_today(token, engine, chat_id)
        return
    if "id сделки" in text.lower():
        result = _ingest(engine, text)
        if message is not None and chat_id is not None and result == "created":
            order_data = parse_order_text(text)
            client_name = mask_name(order_data["client_name"]) or "не указано"
            address = mask_address(order_data["address"]) or "не указано"
            reason = order_data["reason"] or "не указано"
            confirmation = f"✅ Заявка принята: {client_name}, {address} ({reason})"
            _send_message(token, chat_id, confirmation)
        elif message is not None and chat_id is not None and result == "duplicate":
            _send_message(token, chat_id, "ℹ️ Заявка уже в системе")
        return
    chat = message.get("chat") if message is not None else {}
    if (
        message is not None
        and actor_key is not None
        and (chat or {}).get("type") == "private"
        and not _handle_master_text(token, engine, message, actor_key)
    ):
        _handle_agent_message(token, engine, message)


def _loop(token: str, engine) -> None:
    offset = _load_offset()
    allowed_roles = _allowed_sender_roles()
    while True:
        try:
            url = (
                "https://api.telegram.org/bot"
                + token
                + "/getUpdates?timeout=5&offset="
                + str(offset)
            )
            with urllib.request.urlopen(url, timeout=15) as r:
                payload = json.loads(r.read().decode("utf-8"))
            updates = payload.get("result", [])
            if updates:
                print(f"tg updates: {len(updates)}")
            for update in updates:
                offset = max(offset, update["update_id"] + 1)
                _process_update(token, engine, update, allowed_roles)
            _save_offset(offset)
        except Exception:
            traceback.print_exc()
            time.sleep(3)
        time.sleep(2)


def start_poller(engine) -> None:
    global _poller_started

    token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    if not token:
        _poller_started = False
        print("TG poller: token not set, skip")
        return
    thread = threading.Thread(target=_loop, args=(token, engine), daemon=True)
    thread.start()
    _poller_started = True
    print("TG poller: started")


def poller_started() -> bool:
    """Вернуть фактический процесс-локальный статус запуска поллера."""
    return _poller_started
