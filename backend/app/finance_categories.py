"""Детерминированные статьи финансов Ekodez Core, словарь v1."""

from collections.abc import Mapping


EXPENSE_CATEGORY_KEYWORDS_V1: Mapping[str, tuple[str, ...]] = {
    "Материалы и химия": ("хими", "chemical", "материал", "расходник"),
    "Топливо и транспорт": ("бензин", "топливо", "такси"),
    "Аренда": ("аренд",),
    "Реклама": ("реклам",),
    "Зарплата и авансы": ("зарплат", "аванс"),
    "Оборудование": ("оборудован",),
}

INCOME_CATEGORY_KEYWORDS_V1: Mapping[str, tuple[str, ...]] = {
    "Услуги: удаление запахов": ("запах", "озон"),
    "Дезинфекция": ("дезинфекц",),
    "Дезинсекция": ("дезинсекц", "насеком"),
    "Дератизация": ("дератиз", "грызун"),
}

CATEGORY_KEYWORDS_V1 = (
    *EXPENSE_CATEGORY_KEYWORDS_V1.items(),
    *INCOME_CATEGORY_KEYWORDS_V1.items(),
)


def classify_finance(text: str) -> str | None:
    """Вернуть первую подходящую статью по упорядоченному словарю v1."""
    normalized = text.lower()
    for category, keywords in CATEGORY_KEYWORDS_V1:
        if any(keyword in normalized for keyword in keywords):
            return category
    return None
