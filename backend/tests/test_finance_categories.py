import unittest

from app.finance_categories import (
    EXPENSE_CATEGORIES_V1,
    INCOME_CATEGORIES_V1,
    classify_finance,
    default_finance_category,
)


class FinanceCategoriesTest(unittest.TestCase):
    def test_income_categories_are_exact(self):
        self.assertEqual(
            INCOME_CATEGORIES_V1,
            (
                "Химчистка",
                "Дезинсекция",
                "Дератизация",
                "Дезинфекция",
                "Обработка от клещей",
                "Клининг",
                "Юридические клиенты",
                "Доход от агрегаторов",
                "Плесень",
                "Другие работы",
            ),
        )

    def test_expense_categories_match_seed_catalog(self):
        self.assertEqual(
            EXPENSE_CATEGORIES_V1,
            (
                "Еда",
                "Топливо и машина",
                "Материалы и химия",
                "Реклама",
                "Оборудование и инструмент",
                "СИЗ",
                "Прочее",
            ),
        )

    def test_classifies_requested_keywords_case_insensitively(self):
        cases = {
            "химчистка дивана": "Химчистка",
            "химчист ковра": "Химчистка",
            "дезинфекция помещения": "Дезинфекция",
            "санобработка помещения": "Дезинфекция",
            "обработка от тараканов": "Дезинсекция",
            "уничтожение клопов": "Дезинсекция",
            "обработка от крыс": "Дератизация",
            "защита от грызунов": "Дератизация",
            "обработка участка от клещей": "Обработка от клещей",
            "акарицидная обработка": "Обработка от клещей",
            "генеральный клининг": "Клининг",
            "уборка помещения": "Клининг",
            "договор с юридическим лицом": "Юридические клиенты",
            "выплата агрегатора": "Доход от агрегаторов",
            "удаление плесени": "Плесень",
            "обработка от грибка": "Плесень",
            "еда в дороге": "Еда",
            "кафе": "Еда",
            "продукты": "Еда",
            "поели": "Еда",
            "бензин": "Топливо и машина",
            "оплатил топливо": "Топливо и машина",
            "заправка": "Топливо и машина",
            "такси до клиента": "Топливо и машина",
            "Купил ХИМИЮ": "Материалы и химия",
            "материалы для обработки": "Материалы и химия",
            "расходники": "Материалы и химия",
            "оплатил рекламу": "Реклама",
            "купил оборудование": "Оборудование и инструмент",
            "новый инструмент": "Оборудование и инструмент",
            "защитные СИЗ": "СИЗ",
            "купил респиратор": "СИЗ",
        }

        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(classify_finance(text), expected)

    def test_returns_none_when_no_keyword_matches(self):
        self.assertIsNone(classify_finance("обычная операция без категории"))

    def test_first_rule_wins_when_multiple_categories_match(self):
        self.assertEqual(
            classify_finance("еда и бензин"),
            "Еда",
        )

    def test_kind_specific_fallbacks(self):
        self.assertEqual(default_finance_category("income"), "Другие работы")
        self.assertEqual(default_finance_category("expense"), "Прочее")
        self.assertEqual(default_finance_category("unknown"), "Прочее")


if __name__ == "__main__":
    unittest.main()
