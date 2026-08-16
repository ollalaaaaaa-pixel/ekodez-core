import unittest
from unittest.mock import patch

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import main
from app.models import Base, ExpenseCategory


class ExpenseCategoriesApiTest(unittest.TestCase):
    def setUp(self):
        self.original_engine = main.engine
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        main.engine = self.engine

    def tearDown(self):
        main.engine = self.original_engine
        self.engine.dispose()

    def test_create_trims_name_and_list_returns_only_active_in_id_order(self):
        created = main.create_expense_category(
            main.ExpenseCategoryIn(name="  Аренда склада  ")
        )
        with Session(self.engine) as session:
            session.add(ExpenseCategory(name="Скрытая", is_active=False))
            session.add(ExpenseCategory(name="Реклама"))
            session.commit()

        rows = main.list_expense_categories()

        self.assertEqual(created.name, "Аренда склада")
        self.assertEqual([row.name for row in rows], ["Аренда склада", "Реклама"])

    def test_duplicate_is_rejected_case_insensitively(self):
        main.create_expense_category(main.ExpenseCategoryIn(name="Аренда склада"))

        with self.assertRaises(HTTPException) as context:
            main.create_expense_category(
                main.ExpenseCategoryIn(name="аренда склада")
            )

        self.assertEqual(context.exception.status_code, 400)

    def test_empty_or_too_long_name_is_rejected(self):
        for name in ("   ", "x" * 101):
            with self.subTest(name_length=len(name)):
                with self.assertRaises(HTTPException) as context:
                    main.create_expense_category(
                        main.ExpenseCategoryIn(name=name)
                    )
                self.assertEqual(context.exception.status_code, 422)

    def test_integrity_error_is_reported_as_duplicate(self):
        main.create_expense_category(main.ExpenseCategoryIn(name="Аренда склада"))

        with patch.object(Session, "scalars") as scalars:
            scalars.return_value.all.return_value = []
            with self.assertRaises(HTTPException) as context:
                main.create_expense_category(
                    main.ExpenseCategoryIn(name="Аренда склада")
                )

        self.assertEqual(context.exception.status_code, 400)
        self.assertIsInstance(context.exception.__cause__, IntegrityError)


if __name__ == "__main__":
    unittest.main()
