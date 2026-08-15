import unittest

from app.finance_categories import classify_finance, default_finance_category


class FinanceCategoriesTest(unittest.TestCase):
    def test_classifies_requested_keywords_case_insensitively(self):
        cases = {
            "химчистка дивана": "Химчистка",
            "химчист ковра": "Химчистка",
            "дезинфекция помещения": "Дезинфекция",
            "санобработка помещения": "Дезинфекция",
            "еда в дороге": "Еда",
            "кафе": "Еда",
            "продукты": "Еда",
            "поели": "Еда",
            "бензин": "Топливо и машина",
            "оплатил топливо": "Топливо и машина",
            "заправка": "Топливо и машина",
            "такси до клиента": "Топливо и машина",
            "Купил ХИМИЮ": "Материалы",
            "материалы для обработки": "Материалы",
            "расходники": "Материалы",
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
        self.assertEqual(default_finance_category("expense"), "Другое")
        self.assertEqual(default_finance_category("unknown"), "Другое")


if __name__ == "__main__":
    unittest.main()
