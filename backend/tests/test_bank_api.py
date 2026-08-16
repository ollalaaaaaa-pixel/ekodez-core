import unittest
from datetime import date
from io import BytesIO
from typing import Any, cast

from fastapi.testclient import TestClient
from openpyxl import Workbook
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app import main
from app.models import Base, ExpenseCategory, Transaction

HEADERS = (
    "Тип операции",
    "Дата проведения",
    "Номер документа",
    "Сумма в валюте счёта",
    "Описание операции",
    "Назначение платежа",
    "Наименование контрагента",
    "ИНН контрагента",
)


def statement_bytes(*rows: tuple[object, ...]) -> bytes:
    workbook = Workbook()
    sheet = workbook.worksheets[0]
    sheet.append(("Синтетическая выписка",))
    sheet.append(HEADERS)
    for row in rows:
        sheet.append(cast(list[Any], list(row)))
    output = BytesIO()
    workbook.save(output)
    return output.getvalue()


def preview(client: TestClient, *rows: tuple[object, ...]) -> list[dict[str, object]]:
    response = client.post(
        "/api/bank/preview",
        files={
            "file": (
                "synthetic.xlsx",
                statement_bytes(*rows),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
    )
    if response.status_code != 200:
        raise AssertionError(response.text)
    return response.json()


class BankImportApiTest(unittest.TestCase):
    def setUp(self):
        self.original_engine = main.engine
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        main.engine = self.engine
        with Session(self.engine) as session:
            session.add_all(
                ExpenseCategory(name=name)
                for name in (
                    "Материалы и химия",
                    "Налоги и взносы",
                    "Банковские комиссии",
                    "Прочее",
                )
            )
            session.commit()
        self.client = TestClient(main.app)

    def tearDown(self):
        self.client.close()
        main.engine = self.original_engine
        self.engine.dispose()

    def test_preview_returns_server_classification_hash_and_masked_inn(self):
        rows = preview(
            self.client,
            (
                "Кредит",
                date(2026, 8, 15),
                "101",
                "1 500 000,50",
                "Резервное описание",
                "Оплата дератизации",
                "ООО Синтетика",
                "2901000000",
            ),
            (
                "Дебет",
                date(2026, 8, 16),
                "102",
                "27,544.00",
                "Комиссия",
                "",
                "ТБанк",
                "",
            ),
        )

        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["amount"], "1500000.50")
        self.assertEqual(rows[0]["category"], "Дератизация")
        self.assertEqual(rows[0]["channel"], "Прочее")
        self.assertEqual(rows[0]["comment"], "Оплата дератизации")
        self.assertEqual(rows[0]["counterparty_inn_masked"], "******0000")
        self.assertNotIn("2901000000", str(rows[0]["counterparty_inn_masked"]))
        self.assertEqual(len(str(rows[0]["source_hash"])), 64)
        self.assertFalse(rows[0]["needs_review"])
        self.assertFalse(rows[0]["is_transfer"])
        self.assertEqual(rows[1]["amount"], "27544.00")
        self.assertEqual(rows[1]["category"], "Банковские комиссии")
        self.assertEqual(rows[1]["comment"], "Комиссия")

    def test_preview_rejects_non_xlsx_and_corrupt_xlsx(self):
        wrong_extension = self.client.post(
            "/api/bank/preview",
            files={"file": ("statement.csv", b"x", "text/csv")},
        )
        corrupt = self.client.post(
            "/api/bank/preview",
            files={
                "file": (
                    "statement.xlsx",
                    b"PII-MARKER-2901000000",
                    "application/octet-stream",
                )
            },
        )

        self.assertEqual(wrong_extension.status_code, 400)
        self.assertEqual(corrupt.status_code, 400)
        self.assertNotIn("2901000000", corrupt.json()["detail"])

    def test_preview_returns_actionable_header_diagnostics(self):
        workbook = Workbook()
        sheet = workbook.worksheets[0]
        for row_number in range(1, 10):
            sheet.append((f"Сводка {row_number}",))
        sheet.append(
            (
                "Тип операции",
                "Дата проведения",
                "Номер документа",
                "Сумма в валюте счета",
                "Описание операции",
                "Назначение платежа",
                "Наименование плательщика",
            )
        )
        output = BytesIO()
        workbook.save(output)

        response = self.client.post(
            "/api/bank/preview",
            files={
                "file": (
                    "diagnostic.xlsx",
                    output.getvalue(),
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )
            },
        )

        self.assertEqual(response.status_code, 400)
        detail = response.json()["detail"]
        self.assertEqual(detail["message"], "required columns not found")
        self.assertEqual(detail["searched_row"], 10)
        self.assertIn("тип операции", detail["found_columns"])
        self.assertIn("наименование контрагента", detail["missing_columns"])
        self.assertIn("инн контрагента", detail["missing_columns"])

    def test_confirm_rejects_hash_tampering_and_invalid_review_decisions(self):
        review_row = preview(
            self.client,
            (
                "Кредит",
                date(2026, 8, 15),
                "201",
                "1000.00",
                "Описание",
                "Обычная услуга",
                "ООО Синтетика",
                "2901000000",
            ),
        )[0]

        tampered = dict(review_row, source_hash="0" * 64)
        no_confirmation = dict(
            review_row,
            category_override="Другие работы",
            review_confirmed=False,
        )
        no_override = dict(review_row, review_confirmed=True)
        invalid_override = dict(
            review_row,
            category_override="Несуществующая статья",
            review_confirmed=True,
        )

        for row in (tampered, no_confirmation, no_override, invalid_override):
            with self.subTest(row=row):
                response = self.client.post(
                    "/api/bank/confirm",
                    json={"source_filename": "synthetic.xlsx", "transactions": [row]},
                )
                self.assertEqual(response.status_code, 422)

    def test_confirm_rejects_override_for_confident_row(self):
        row = preview(
            self.client,
            (
                "Кредит",
                date(2026, 8, 15),
                "202",
                "1000.00",
                "Описание",
                "Оплата химчистки",
                "Контрагент",
                "",
            ),
        )[0]
        row["category_override"] = "Другие работы"
        row["review_confirmed"] = True

        response = self.client.post(
            "/api/bank/confirm",
            json={"source_filename": "synthetic.xlsx", "transactions": [row]},
        )

        self.assertEqual(response.status_code, 422)

    def test_confirm_is_idempotent_and_reconciles_bank_turnovers(self):
        rows = preview(
            self.client,
            (
                "Кредит",
                date(2026, 8, 15),
                "301",
                "100000.00",
                "Оплата",
                "Оплата химчистки",
                "Клиент",
                "",
            ),
            (
                "Дебет",
                date(2026, 8, 15),
                "302",
                "50000.00",
                "Дез средства",
                "Оплата материалов",
                "МЕДИЛИС",
                "",
            ),
            (
                "Кредит",
                date(2026, 8, 15),
                "303",
                "497562.80",
                "Перевод",
                "Перевод собственных средств",
                "Владелец",
                "",
            ),
            (
                "Дебет",
                date(2026, 8, 15),
                "304",
                "547562.66",
                "Перевод",
                "Перевод собственных средств",
                "Владелец",
                "",
            ),
        )
        payload = {"source_filename": "synthetic.xlsx", "transactions": rows}

        first_response = self.client.post("/api/bank/confirm", json=payload)
        second_response = self.client.post("/api/bank/confirm", json=payload)

        self.assertEqual(first_response.status_code, 200, first_response.text)
        self.assertEqual(second_response.status_code, 200, second_response.text)
        first = first_response.json()
        second = second_response.json()
        self.assertEqual(first["imported"], 2)
        self.assertEqual(first["skipped_duplicates"], 0)
        self.assertEqual(first["imported_income_amount"], "100000.00")
        self.assertEqual(first["imported_expense_amount"], "50000.00")
        self.assertEqual(first["excluded_credit_amount"], "497562.80")
        self.assertEqual(first["excluded_debit_amount"], "547562.66")
        self.assertEqual(first["statement_credit_total"], "597562.80")
        self.assertEqual(first["statement_debit_total"], "597562.66")
        self.assertTrue(first["credit_reconciled"])
        self.assertTrue(first["debit_reconciled"])
        self.assertEqual(second["imported"], 0)
        self.assertEqual(second["skipped_duplicates"], 2)
        self.assertEqual(second["duplicate_income_amount"], "100000.00")
        self.assertEqual(second["duplicate_expense_amount"], "50000.00")
        self.assertEqual(second["statement_credit_total"], "597562.80")
        self.assertEqual(second["statement_debit_total"], "597562.66")
        self.assertTrue(second["credit_reconciled"])
        self.assertTrue(second["debit_reconciled"])

        with Session(self.engine) as session:
            self.assertEqual(session.scalar(select(func.count(Transaction.id))), 2)
            imported = session.scalars(
                select(Transaction).order_by(Transaction.id)
            ).all()
        self.assertEqual(imported[0].source, "tbank")
        self.assertEqual(imported[0].description, "Оплата химчистки")
        self.assertFalse(imported[0].review_required)
        self.assertFalse(imported[0].needs_review)
        self.assertIsNotNone(imported[0].import_batch_id)

    def test_review_override_is_saved_but_original_review_flag_is_retained(self):
        row = preview(
            self.client,
            (
                "Дебет",
                date(2026, 8, 15),
                "401",
                "900.00",
                "Покупка",
                "Неизвестный расход",
                "Поставщик",
                "",
            ),
        )[0]
        row["category_override"] = "Прочее"
        row["review_confirmed"] = True

        response = self.client.post(
            "/api/bank/confirm",
            json={"source_filename": "synthetic.xlsx", "transactions": [row]},
        )

        self.assertEqual(response.status_code, 200, response.text)
        with Session(self.engine) as session:
            saved = session.scalar(select(Transaction))
        self.assertIsNotNone(saved)
        assert saved is not None
        self.assertEqual(saved.category, "Прочее")
        self.assertTrue(saved.needs_review)
        self.assertFalse(saved.review_required)


if __name__ == "__main__":
    unittest.main()
