"""Детерминированные статьи финансов Ekodez Core, словарь v1."""

from collections.abc import Mapping

INCOME_CATEGORY_KEYWORDS_V1: Mapping[str, tuple[str, ...]] = {
    "Химчистка": ("химчист",),
    "Дезинсекция": ("дезинсек", "таракан", "клоп", "насеком"),
    "Дератизация": ("дератиз", "крыс", "мыш", "грызун"),
    "Дезинфекция": ("дезинфек", "санобработ"),
    "Обработка от клещей": ("клещ", "акарицид"),
    "Клининг": ("клининг", "уборк"),
    "Юридические клиенты": ("юридическ", "юрлиц", "договор"),
    "Доход от агрегаторов": ("агрегатор",),
    "Плесень": ("плесен", "грибк"),
}

EXPENSE_CATEGORY_KEYWORDS_V1: Mapping[str, tuple[str, ...]] = {
    "Еда": ("еда", "кафе", "продукт", "поели"),
    "Топливо и машина": ("бензин", "топливо", "заправ", "такси"),
    "Материалы и химия": ("хими", "материал", "расходник"),
    "Реклама": ("реклам",),
    "Оборудование и инструмент": ("оборудован", "инструмент"),
    "СИЗ": ("сиз", "перчат", "респиратор", "защитн", "маск"),
}

CATEGORY_KEYWORDS_V1 = (
    *INCOME_CATEGORY_KEYWORDS_V1.items(),
    *EXPENSE_CATEGORY_KEYWORDS_V1.items(),
)

INCOME_CATEGORIES_V1 = (*INCOME_CATEGORY_KEYWORDS_V1, "Другие работы")
EXPENSE_CATEGORIES_V1 = (*EXPENSE_CATEGORY_KEYWORDS_V1, "Прочее")


def classify_finance(text: str) -> str | None:
    """Вернуть первую подходящую статью по упорядоченному словарю v1."""
    normalized = text.lower()
    for category, keywords in CATEGORY_KEYWORDS_V1:
        if any(keyword in normalized for keyword in keywords):
            return category
    return None


def default_finance_category(kind: str) -> str:
    """Вернуть утверждённую статью по умолчанию для направления операции."""
    return "Другие работы" if kind == "income" else "Прочее"
