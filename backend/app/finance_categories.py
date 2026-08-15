"""Детерминированные статьи финансов Ekodez Core, словарь v1."""

from collections.abc import Mapping


INCOME_CATEGORY_KEYWORDS_V1: Mapping[str, tuple[str, ...]] = {
    "Химчистка": ("химчист",),
    "Дезинфекция": ("дезинфек", "санобработ"),
}

EXPENSE_CATEGORY_KEYWORDS_V1: Mapping[str, tuple[str, ...]] = {
    "Еда": ("еда", "кафе", "продукт", "поели"),
    "Топливо и машина": ("бензин", "топливо", "заправ", "такси"),
    "Материалы": ("хими", "материал", "расходник"),
}

CATEGORY_KEYWORDS_V1 = (
    *INCOME_CATEGORY_KEYWORDS_V1.items(),
    *EXPENSE_CATEGORY_KEYWORDS_V1.items(),
)

INCOME_CATEGORIES_V1 = (*INCOME_CATEGORY_KEYWORDS_V1, "Другие работы")
EXPENSE_CATEGORIES_V1 = (*EXPENSE_CATEGORY_KEYWORDS_V1, "Другое")


def classify_finance(text: str) -> str | None:
    """Вернуть первую подходящую статью по упорядоченному словарю v1."""
    normalized = text.lower()
    for category, keywords in CATEGORY_KEYWORDS_V1:
        if any(keyword in normalized for keyword in keywords):
            return category
    return None


def default_finance_category(kind: str) -> str:
    """Вернуть утверждённую статью по умолчанию для направления операции."""
    return "Другие работы" if kind == "income" else "Другое"
