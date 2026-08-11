import re
from datetime import datetime


def _field(text: str, label: str) -> str:
    pattern = re.compile(re.escape(label) + r"\s*(.*?)(?=\n|$)", re.IGNORECASE)
    m = pattern.search(text)
    return m.group(1).strip() if m else ""


def parse_order_text(text: str) -> dict:
    data = {
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
