import re
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import TypedDict


class OrderData(TypedDict):
    external_id: str
    client_name: str
    phone: str
    address: str
    area: str
    reason: str
    comment: str
    amount_note: str
    contract: str
    partner: str
    order_at: datetime | None


def _field(text: str, label: str) -> str:
    pattern = re.compile(re.escape(label) + r"\s*(.*?)(?=\n|$)", re.IGNORECASE)
    m = pattern.search(text)
    return m.group(1).strip() if m else ""


def parse_order_text(text: str) -> OrderData:
    data: OrderData = {
        "external_id": _field(text, "id сделки:"),
        "client_name": _field(text, "Имя клиента:"),
        "phone": _field(text, "Телефон:"),
        "address": _field(text, "Адрес:"),
        "area": _field(text, "Площадь:"),
        "reason": _field(text, "Причина обращения:"),
        "comment": _field(text, "Комментарий:"),
        "amount_note": _field(text, "Сумма:"),
        "contract": _field(text, "Договор:"),
        "partner": _field(text, "Вы напарник:"),
        "order_at": None,
    }
    dt = _field(text, "Дата и время:")
    if dt:
        try:
            data["order_at"] = datetime.strptime(dt, "%d.%m.%Y %H:%M")
        except ValueError:
            data["order_at"] = None
    return data


def parse_amount_note(value: str | None) -> Decimal:
    """Parse the legacy free-text lead amount without making ingest fail."""
    normalized = (value or "").replace("\u00a0", "").replace(" ", "").replace(",", ".")
    try:
        amount = Decimal(normalized)
    except InvalidOperation:
        return Decimal("0.00")
    if not amount.is_finite() or amount < 0:
        return Decimal("0.00")
    quantized = amount.quantize(Decimal("0.01"))
    return quantized if quantized == amount else Decimal("0.00")
