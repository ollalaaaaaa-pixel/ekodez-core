import unittest

from app.finance_categories import classify_finance


class FinanceCategoriesTest(unittest.TestCase):
    def test_classifies_requested_keywords_case_insensitively(self):
        cases = {
            "Купил ХИМИЮ": "Материалы и химия",
            "Chemicals": "Материалы и химия",
            "материалы для обработки": "Материалы и химия",
            "расходники": "Материалы и химия",
            "бензин": "Топливо и транспорт",
            "оплатил топливо": "Топливо и транспорт",
            "такси до клиента": "Топливо и транспорт",
            "аренда склада": "Аренда",
            "реклама в интернете": "Реклама",
            "зарплата сотруднику": "Зарплата и авансы",
            "аванс сотруднику": "Зарплата и авансы",
            "новое оборудование": "Оборудование",
            "удаление запаха": "Услуги: удаление запахов",
            "озон": "Услуги: удаление запахов",
            "дезинфекция помещения": "Дезинфекция",
            "дезинсекция кухни": "Дезинсекция",
            "насекомые": "Дезинсекция",
            "дератизация склада": "Дератизация",
            "грызуны": "Дератизация",
        }

        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(classify_finance(text), expected)

    def test_returns_none_when_no_keyword_matches(self):
        self.assertIsNone(classify_finance("обычная операция без категории"))

    def test_first_rule_wins_when_multiple_categories_match(self):
        self.assertEqual(
            classify_finance("химия и бензин"),
            "Материалы и химия",
        )


if __name__ == "__main__":
    unittest.main()
