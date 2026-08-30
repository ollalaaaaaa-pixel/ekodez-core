"""Стабильные внутренние значения источников заявки и подписи для UI."""

LEAD_SOURCE_LABELS: dict[str, str] = {
    "telegram": "Telegram-бот",
    "aggregators": "Агрегаторы",
    "other": "Другое",
}

LEAD_SOURCES = tuple(LEAD_SOURCE_LABELS)
