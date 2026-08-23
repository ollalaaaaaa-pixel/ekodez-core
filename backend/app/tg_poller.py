import json
import os
import re
import sys
import threading
import time
import traceback
import urllib.parse
import urllib.request
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.finance_categories import classify_finance, default_finance_category
from app.lead_parser import parse_order_text
from app.models import Lead, Transaction
from app.security.pii import mask_address, mask_name, protect_lead_pii

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
    allowed: set[int] = set()
    for name in ("OWNER_TG_ID", "ALEXEY_TG_ID"):
        value = os.getenv(name, "").strip()
        if value:
            try:
                allowed.add(int(value))
            except ValueError:
                print(f"TG agent: {name} is not numeric, ignored", file=sys.stderr)
    return allowed


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


def _loop(token: str, engine) -> None:
    offset = _load_offset()
    allowed_ids = _allowed_sender_ids()
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
                callback = update.get("callback_query")
                if callback is not None:
                    _handle_callback(token, engine, callback, allowed_ids)
                    continue
                channel_post = update.get("channel_post")
                message = update.get("message")
                msg = channel_post or message or {}
                text = msg.get("text") or ""
                command = text.split(maxsplit=1)[0].split("@")[0] if text else ""
                if message is not None and command == "/whoami":
                    chat_id = (message.get("chat") or {}).get("id")
                    if chat_id is not None:
                        _send_message(token, chat_id, str(chat_id))
                    continue
                if "id сделки" in text.lower():
                    result = _ingest(engine, text)
                    if message is not None:
                        chat_id = (message.get("chat") or {}).get("id")
                        if chat_id is not None and result == "created":
                            data = parse_order_text(text)
                            client_name = mask_name(data["client_name"]) or "не указано"
                            address = mask_address(data["address"]) or "не указано"
                            reason = data["reason"] or "не указано"
                            confirmation = (
                                f"✅ Заявка принята: {client_name}, "
                                f"{address} ({reason})"
                            )
                            _send_message(token, chat_id, confirmation)
                        elif chat_id is not None and result == "duplicate":
                            _send_message(
                                token,
                                chat_id,
                                "ℹ️ Заявка уже в системе",
                            )
                elif message is not None:
                    chat = message.get("chat") or {}
                    sender_id = (message.get("from") or {}).get("id")
                    if chat.get("type") == "private" and sender_id in allowed_ids:
                        _handle_agent_message(token, engine, message)
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
