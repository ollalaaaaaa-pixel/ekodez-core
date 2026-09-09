"""Стабильные внутренние значения источников заявки и подписи для UI."""

LEAD_SOURCE_LABELS: dict[str, str] = {
    "telegram": "Telegram-бот",
    "aggregators": "Агрегаторы",
    "other": "Другое",
    "yandex_direct": "Яндекс Директ",
    "vk": "ВКонтакте",
    "avito": "Авито",
    "seo": "Поиск (SEO)",
}

LEAD_SOURCES = tuple(LEAD_SOURCE_LABELS)

UTM_SOURCES = {
    "yandex": "yandex_direct",
    "yandex_direct": "yandex_direct",
    "vk": "vk",
    "avito": "avito",
    "seo": "seo",
}


def source_from_utm(value: str | None, fallback: str) -> str:
    return UTM_SOURCES.get((value or "").strip().lower(), fallback)
